## Context

- The one-line installers (`scripts/install-pc.sh`, `install-pc.ps1`) find or install uv, read the newest version from the `releases/latest` redirect, skip an install that is already current, and run `uv tool install --force --compile-bytecode --python <V> --overrides <pytest dropped> "canworks @ <release wheel URL>"`, then `canworks-config --create-shortcut`.
- The configurator is one background process per user, found through `instance.json` (pid, port, secret) in the settings folder. It stops on Quit or when its last tab closes. Pages carry a session token in a cookie, swapped from a one-time code in the start URL.
- The shortcuts point at paths that survive a reinstall: the tool environment's `pythonw.exe` on Windows, the `canworks-config` launcher on macOS and Linux.
- uv writes `uv-receipt.toml` into each tool environment (requirements, entry points, Python request). Checked with uv 0.11: when resolving fails (an unknown version, a missing package), `uv tool install --force` leaves the old environment as it was.
- Windows does not let a file in use be deleted. A running configurator holds the environment's `pythonw.exe` launcher and every loaded extension module (`.pyd`) in it. So does `canworks-diag` or a simulator started from the same install.
- Release retention keeps the newest 4 releases, so the version before an update can normally still be downloaded.

## Goals / Non-Goals

**Goals:**
- Tell the user about a newer release without getting in the way.
- Update with one click on Windows, macOS and Linux, without a terminal or admin rights, and without losing the open tab.
- Never leave a broken install: either the new version runs, or the old one does and the user is told why.
- Nothing new for antivirus or Gatekeeper to flag: no downloaded script runs, and there is no new executable to sign.

**Non-Goals:**
- Updating uv itself or moving to another Python (the one-line installer keeps doing that).
- Updating the plugin or bridge on devices (the Devices panel does that) or the local simulator runtime image (`canworks-sim-runtime update`). The "Updated" message mentions the latter when a local runtime exists.
- Update hints in the other commands (`canworks-diag`, `canworks-deploy`).
- Checksums for the wheel beyond TLS (possible later with a `SHA256SUMS` release asset).
- Installs that are not uv tools (a developer checkout, pip in a venv): they get the badge only.

## Decisions

**1. The check: the `releases/latest` redirect, once a day.**
`update.check()` sends `GET <repo>/releases/latest` with redirects off and a `canworks-config/<version>` User-Agent, and reads the tag from `Location` (`deploy-v<version>`). The API is not used: no token and no rate limit. The result and its time go to `update.json` in the settings folder. A new check happens at start when the last one is older than 24 h, or on "Check now". It runs in a thread and never delays the page. Offline, a proxy refusal or an odd answer: no badge, one log line. Python's `urllib` follows the system proxy settings, and on Windows it uses the system certificate store, so a company proxy normally works.

The switch lives in `ui.json` (`update_check`, default on). `CANWORKS_NO_UPDATE_CHECK=1` turns it off as well, and the test suites and CI workflows set it. The page shows the badge only when the newest version is greater than the running one (compared as version numbers) and not dismissed. Dismissing is stored per version, so the next release shows again.

Alternatives: the GitHub API (rate limited at 60 requests per hour per address without a token, more data than needed); a check on every start (releases come several times a day, and a slow network would show).

**2. Who can update: install detection.**
`update.install_kind()` returns:
- `uv-tool` when `sys.prefix` has `uv-receipt.toml` and lies under `uv tool dir`, and uv is found (PATH, then `~/.local/bin`, then `~/.cargo/bin`, as in the installers).
- `sandboxed` on Windows when `sys.prefix` lies under `%LOCALAPPDATA%\Packages\` (an install made inside another app's MSIX sandbox, whose AppData is private to that app).
- `other` otherwise.

Only `uv-tool` gets the Update button. The others get the one-line install command for their system with a Copy button, plus for `sandboxed` the note "run it from your own PowerShell".

**3. Quit first, then install, on every OS.**
On Windows this is required. On macOS and Linux the files could be replaced under a running process, but the configurator imports parts of itself late, and a running process would then mix old and new modules. One flow for all three is simpler to test.

**4. The updater runs outside the environment it replaces.**
`canworks/updater.py` uses only the standard library. To start it, the configurator copies it to a new temporary folder and starts it with the base interpreter behind the tool environment (`sys._base_executable`; on Windows its `pythonw.exe`), with `-I -S` so that nothing from the tool environment or the current folder is imported. The base interpreter lives in uv's Python folder, which a tools reinstall does not touch. It starts detached like `launch.spawn` (Windows: `DETACHED_PROCESS | CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`, plus `CREATE_BREAKAWAY_FROM_JOB` when the job allows it, retried without it; elsewhere a new session).

Alternative rejected: download and run the release's `install-pc.ps1` / `install-pc.sh`. That is one code path with the installers, but on Windows it means a hidden Python starting PowerShell on a downloaded script, which is the pattern the Windows installer change removed because Defender flagged it. The cost of calling uv directly is that the uv arguments live in two places. A test reads both scripts and `updater.py` and fails when the `uv tool install` arguments differ.

**5. The hand-off.**
The configurator writes `update-run.json` in the settings folder (user-readable only, like `instance.json`): target version, old version, both wheel URLs, Python request (from the receipt, or the running interpreter's `major.minor`), uv path, the tools' environment and bin folder, the commands to check the installed version and to start the configurator again, the configurator's pid, its port and its session token. It starts the updater with the file's path, answers the page `{"updating": true}`, and stops as Quit does. The page shows "Updating to 0.x.0. This tab comes back by itself." and polls the same address every second.

**6. The updater's steps.**
1. Wait for the pid to end (30 s, then give up and start nothing: the old configurator still runs).
2. Windows only, the lock probe: open each program file of the tool environment (`.exe`, `.dll`, `.pyd`) for writing and close it again. Windows refuses that while a process runs or has loaded the file, which is also what makes uv fail to remove it. (Renaming the folder, the first idea, is no probe: the Windows CI runner renamed it while a tools process ran from it, and uv then failed halfway through.) On failure it retries for 10 s, then stops with "Close canworks-diag and other canworks windows, then press Update again" and starts the old configurator again.
3. `uv tool install --force --compile-bytecode --python <P> --overrides <file> "canworks @ <wheel URL>"`, with the user's environment (so `UV_SYSTEM_CERTS` and proxy variables apply). Output goes to `update.log` next to `configurator.log` (one older file kept).
4. macOS and Linux: `canworks-config --create-shortcut` from the bin folder when the shortcut exists (not fatal). The Windows `.lnk` files point at the environment's `pythonw.exe` and its icon, paths a reinstall keeps, and writing them needs PowerShell, which the updater does not start.
5. Start the new configurator as the shortcut does (`canworks-config --from-shortcut`, on Windows the environment's `pythonw.exe -m canworks.configurator.start --from-shortcut`) with `--resume <update-run.json>`, without a browser of its own. Only for Update now: after Update when I quit, nothing starts.
6. On a uv failure after uv started: install the old version from its release with the same arguments. If that fails as well, show the platform message window (the one `launch.message_window` uses) with the one-line install command.

The result (`ok`, `failed` with a reason, `rolled-back`) goes into `update-run.json`, and the next configurator start shows it in a message bar ("Updated to 0.x.0" / "Update failed: ... Still on 0.y.0 (update.log)") and then deletes the file.

**7. The open tab comes back.**
With `--resume`, the new configurator takes the port and the session token from the run file when the result is less than 2 minutes old, binds that port when it is free, and removes the file. The old page keeps its token and its cookie (the cookie is per port), so it needs no new start code: it polls `GET /api/update` every second, and when the answer carries another start id (`boot`, new at every start) it reloads. The reloaded page shows the result once (sessionStorage). When the port is taken, the new configurator starts on a new port with a new token and opens a new tab as a shortcut start does; after 3 minutes without an answer the old tab says to use the other tab or start the configurator again. A token in a user-only file for a minute is no weaker than the token in the page and the start URL.

The first idea, a one-time resume code exchanged for a new cookie, was dropped: keeping the token is simpler and needs no new route.

**8. Guard and "Update when I quit".**
`/api/update/start` refuses, with the reason, while: the config has unsaved changes, an online connection or local bus is open, a trace runs, a simulator runs in this process, or a Devices job runs. The page then offers "Update when I quit". That stores the target in the server, and the stop path (Quit, or the last tab closing) runs the hand-off instead of a plain stop. It also covers the case of a tab closed during the 15 s grace time.

**9. `canworks-config --update`.**
Runs the check, prints the current and newest version, and when newer and `uv-tool`: asks a running configurator to update (`/api/instance/update` with the instance secret, which applies the guard) or, when none runs, runs the updater in this terminal (macOS, Linux) and does not start a configurator. On Windows the command's own process holds the tools' files while it runs, so there it starts the updater detached, waiting for its own pid, says that `update.log` shows the progress, and ends. `--update --yes` skips the question; without a terminal and without `--yes` it refuses.

## Risks / Trade-offs

- **[uv removes part of the old environment, then hits a locked file on Windows]** → The lock probe runs right before uv, and the updater waits for the configurator's pid first. If uv still fails, the rollback reinstalls the old version into a fresh environment. A test on the Windows CI runner holds a file open (a `canworks-diag` process) and checks the clean "close other windows" result with the old install intact.
- **[The base interpreter is missing or moved]** → Checked before the hand-off. Without it, Update falls back to the one-line command with Copy.
- **[A company proxy that the check passes but uv does not]** → uv's own message goes to `update.log`, and the failure message names `UV_SYSTEM_CERTS=1`.
- **[The release that is newest has no wheel yet (release still running)]** → uv fails while resolving, which leaves the old install untouched; the message says to try again in a few minutes.
- **[A newer release needs a newer uv or another Python]** → The updater uses the Python of the current install and does not update uv. When uv fails because of it, the message gives the one-line install command, which handles both.
- **[Antivirus heuristics]** → No new executable, no PowerShell, no downloaded script. The processes are uv's own `pythonw.exe` and `uv.exe`, which the installer already ran.
