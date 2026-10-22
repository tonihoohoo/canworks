## 1. Check first

- [ ] 1.1 On the Windows CI runner (dispatch the PC tools workflow on the branch) and on the Windows PC from a normal session: start the configurator from the shortcut, then try to rename its tool environment folder from another process. Confirm that the rename fails while it runs and succeeds after Quit. If it does not fail, change the lock probe in design.md before going on.
- [ ] 1.2 Confirm `sys._base_executable` of the tools' environment points at uv's base interpreter on Windows, macOS and Linux, and that `pythonw.exe` sits next to it on Windows.
- [x] 1.3 Find the first uv version that reads `UV_SYSTEM_CERTS`, for the docs note.
  - Result: uv 0.11.0 (`--native-tls` deprecated in favour of `--system-certs`). The docs name `UV_SYSTEM_CERTS=1` and `UV_NATIVE_TLS=1` for older uv.

## 2. Check and detection

- [x] 2.1 `configurator/update.py`: `check()` (redirect off, User-Agent, tag parse, version compare), the 24 h cache and the dismissed version in `update.json`, `CANWORKS_NO_UPDATE_CHECK`, the `update_check` setting in `ui.json` (default on).
- [x] 2.2 `install_kind()`: `uv-tool` (receipt under `uv tool dir`, uv found, base interpreter exists), `sandboxed` (Windows `%LOCALAPPDATA%\Packages\`), `other`; and the one-line command per system for the Copy fallback.
- [x] 2.3 Server: the background check at start, `GET /api/update` (running, newest, kind, dismissed, last result), `POST /api/update/check`, `POST /api/update/dismiss`.

## 3. Updater

- [x] 3.1 `canworks/updater.py`, standard library only: read `update-run.json`, wait for the pid, Windows rename probe with retry, `uv tool install` with the installers' arguments and the overrides file, `canworks-config --create-shortcut`, start the new configurator with `--resume`, rollback to the old version, the message window as last resort, `update.log` (one older file kept), the result written back.
- [x] 3.2 Hand-off in the server: guard (unsaved changes, online or local bus, trace, simulator, device jobs), `update-run.json` (user-readable only), copy the updater to a temporary folder, start it detached on the base interpreter with `-I -S` (Windows flags, breakaway with fallback), answer the page, stop as Quit.
- [x] 3.3 "Update when I quit": `POST /api/update/on_quit`; the stop path (Quit, last tab closed) runs the hand-off.
- [x] 3.4 `--resume`: bind the old port when free with the old session token (design decision 7: the token is kept instead of a resume code), show the result from `update-run.json` in a message bar and delete it; port taken: new tab as a shortcut start.
- [x] 3.5 `canworks-config --update [--yes]`: versions, question, `/api/instance/update` to a running configurator, else the updater steps in this terminal; exit codes.

## 4. Page

- [x] 4.1 Badge next to the version and on the start page: "0.x.0 available", What's new, Update, dismiss; the Copy-command form for `other` and `sandboxed`.
- [x] 4.2 Updating state: the message, the poll, the reload with the resume code, the "opened in a new tab" text; refusal message with "Update when I quit".
- [x] 4.3 Settings: "Check for updates" switch and "Check now" with the last check time.

## 5. Tests

- [x] 5.1 Unit tests: tag parse and compare, cache and dismissal, environment switch, install detection (fake receipt, fake Packages path), guard reasons, `update-run.json` mode, resume code once and expiry.
- [x] 5.2 Parity test: the `uv tool install` arguments in `install-pc.sh`, `install-pc.ps1` and `updater.py` are the same.
- [ ] 5.3 End-to-end in the PC tools workflow (Windows, macOS, Linux): build wheels of two versions, install the older with the one-line installer, start the configurator `--keep-running`, update to the local newer wheel through a test-only override, check the old pid ends, the new version answers on the same port and the resume code works. On Windows also: with `canworks-diag` held running, the update stops cleanly and the old install still starts. Path-filtered, so other changes do not run it; set `CANWORKS_NO_UPDATE_CHECK=1` in all test jobs.
- [x] 5.4 The fast-start test: `update.py` is not imported by `start.py` on a plain start (start.py imports it only for `--update`; the existing fast-start test passes).

## 6. Docs and version

- [x] 6.1 README.md PC tools section: the update check and Update button, one line on turning the check off.
- [x] 6.2 docs/install-pc.md "Update and uninstall": from the configurator, `--update`, what is sent, `CANWORKS_NO_UPDATE_CHECK`, sandboxed copies; proxy note with `UV_SYSTEM_CERTS=1` (and `UV_NATIVE_TLS=1` for older uv), also in the comments of both install scripts.
- [x] 6.3 `tools/deploy/pyproject.toml` minor version bump; release notes template if it names commands or behaviour that changed.

## 7. Desktop checks (after release; two consecutive releases are needed)

- [ ] 7.1 Windows, Toni's own session (not a Remote Control shell): start from the Start menu shortcut, Update to the next release; the same tab comes back in the new version and the desktop and Start menu shortcuts still work.
- [ ] 7.2 Windows: with `canworks-diag` open in a terminal, Update shows the "close other windows" message and the old version keeps working.
- [ ] 7.3 macOS: Update from the `.app`; the app opens the new version afterwards.
- [ ] 7.4 Linux desktop (or headless): `canworks-config --update --yes` and the Update button.
- [ ] 7.5 "Update when I quit" with unsaved changes on one system: Save, Quit, the next start shows "Updated to".
