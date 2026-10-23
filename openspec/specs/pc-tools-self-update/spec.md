# pc-tools-self-update Specification

## Purpose
The PC tools check for a newer release and update themselves from inside the configurator (or with `canworks-config --update`), on Windows, macOS and Linux, where the one-line installer put them.

## Requirements

### Requirement: Update check

The configurator SHALL find the newest PC tools release from the GitHub `releases/latest` redirect, without the GitHub API or a token. The check SHALL run in the background without delaying the page, and SHALL send nothing but the request with a `canworks-config/<version>` User-Agent. A failed check SHALL show nothing and log one line.

It SHALL check at start when the stored result is older than 1 hour, and otherwise at most once per 24 hours unless the user asks. A stored newest version that is not newer than the installed version SHALL NOT be offered.

#### Scenario: Newer release found
- **WHEN** the configurator 0.101.0 starts, the last check is older than 1 hour, and `releases/latest` redirects to `deploy-v0.102.0`
- **THEN** the page shows a badge "0.102.0 available" next to the version, with a "What's new" link to that release and an Update action, and no dialog opens

#### Scenario: Checked recently
- **WHEN** the configurator starts a second time within 1 hour of a check
- **THEN** no request is sent and the stored result is used

#### Scenario: Stored result outdated
- **WHEN** `update.json` holds 0.124.0 from a check 8 hours ago, the configurator starts, and `releases/latest` now redirects to `deploy-v0.128.3`
- **THEN** the page offers 0.128.3, not 0.124.0

#### Scenario: Offline
- **WHEN** the check cannot reach github.com
- **THEN** no badge and no error bar are shown, and `configurator.log` has one line about it

#### Scenario: Dismissed
- **WHEN** the user dismisses the badge for 0.102.0
- **THEN** it stays hidden for 0.102.0 and shows again when 0.103.0 is the newest release

### Requirement: Update check switch

The check SHALL be on by default and SHALL be turned off by the Settings switch "Check for updates" or by the environment variable `CANWORKS_NO_UPDATE_CHECK=1`. "Check now" in Settings SHALL check once when pressed.

#### Scenario: Check turned off
- **WHEN** `CANWORKS_NO_UPDATE_CHECK=1` is set, or "Check for updates" is off in Settings
- **THEN** no request is sent, and "Check now" in Settings still checks once when pressed

### Requirement: Update only where it can work

The Update action SHALL be offered only for a uv tool install (uv's `uv-receipt.toml` in an environment under `uv tool dir`) with uv found, its base interpreter present, and, on Windows, outside `%LOCALAPPDATA%\Packages\`. Otherwise the badge SHALL show the one-line install command with a Copy button, plus, inside an app's package folder, a note to run it from the user's own PowerShell.

#### Scenario: Developer checkout
- **WHEN** the configurator runs from a virtual environment made with pip and a newer release exists
- **THEN** the badge shows the newer version and the install command, and no Update button

#### Scenario: Copy inside an app's sandbox
- **WHEN** the tools' environment lies under `%LOCALAPPDATA%\Packages\<app>\LocalCache\`
- **THEN** the badge shows the Windows install command and says to run it from the user's own PowerShell

### Requirement: Update from the configurator

Update now SHALL install the newest release and restart the configurator in its new version on every system, without a terminal or admin rights. Right before it starts, it SHALL ask `releases/latest` again and update to the version found then. When that differs from the offered one, the page SHALL name the version it updates to. When GitHub cannot be reached, nothing SHALL stop and the page SHALL say so.

The configurator SHALL stop before anything is installed. An updater on the tools' base interpreter, importing nothing of the tools, SHALL first download the release's wheel and constraints file. It SHALL then call uv with the installers' `uv tool install` arguments on the downloaded wheel, refresh the macOS and Linux shortcut, log to `update.log` and start the new configurator. It SHALL never run an install script.

#### Scenario: Update succeeds
- **WHEN** the configurator 0.101.0 with no unsaved changes and nothing online has Update pressed, and 0.102.0 is the newest release
- **THEN** the page says it is updating, the 0.101.0 process ends, `uv tool list` shows canworks v0.102.0, the shortcut still starts the configurator, and the same tab shows the configurator 0.102.0 with "Updated to 0.102.0"

#### Scenario: Offered release is gone
- **WHEN** the page offers 0.124.0 from an earlier check, that release has been deleted, 0.128.3 is the newest release, and Update is pressed
- **THEN** the page says 0.128.3 is the newest release now, and the configurator updates to 0.128.3

#### Scenario: No script runs
- **WHEN** an update runs on Windows
- **THEN** no PowerShell process is started and no file other than the wheel, its constraints file and its dependencies (fetched by uv) is downloaded

### Requirement: The open tab comes back

After an update the open tab SHALL reload into the new version by itself when the old port is free; otherwise the new version SHALL open in a new tab and the old tab SHALL say so. The next page SHALL show the result in a message bar.

#### Scenario: Port taken
- **WHEN** another program took the old port while the update ran
- **THEN** the new configurator opens a new tab and the old tab says the new version opened in a new tab

### Requirement: Updater matches the installers

The updater's `uv tool install` arguments SHALL stay the same as those of `install-pc.sh` and `install-pc.ps1`, including `--constraints` with the new release's constraints file, downloaded the same way and with the same handling of a release that has none.

#### Scenario: Same arguments as the installers
- **WHEN** the test suite compares the `uv tool install` arguments in `install-pc.sh`, `install-pc.ps1` and the updater
- **THEN** they are the same, and the test fails when one of them changes alone

#### Scenario: Update installs the locked versions
- **WHEN** the configurator updates from 0.110.0 to 0.111.0
- **THEN** the tools' environment has the dependency versions of `canworks-0.111.0-constraints.txt`

### Requirement: Update never leaves a broken install

When an update cannot be done, the user SHALL keep a working install of the version installed before and be told why. The update SHALL NOT need any older release on GitHub.
- The updater SHALL read the installed version before it changes anything. It SHALL never install a version older than or equal to it.
- On Windows it SHALL check before uv runs that no process uses the tools' environment, and stop with a message naming other canworks windows when one does.
- A download that fails SHALL end with nothing changed.
- Before uv runs, the updater SHALL keep the tools' environment as a local copy next to it, and put that copy back when the install fails.

The result SHALL say the install is broken, and show a system message window with the install command, only when the installed tools do not run after that.

#### Scenario: Another tool still running on Windows
- **WHEN** Update is pressed on Windows while `canworks-diag` from the same install still runs in a terminal
- **THEN** nothing is installed, the configurator of the old version starts again, and its page says to close canworks-diag and other canworks windows and press Update again

#### Scenario: Release without its wheel yet
- **WHEN** the newest release has no wheel yet (its download answers 404) and Update is pressed
- **THEN** the install is unchanged, the configurator starts again, and the message says the update could not be downloaded, nothing was changed, and to try again in a few minutes

#### Scenario: Install fails partway
- **WHEN** uv fails after it removed part of the environment, and the old version's release no longer exists on GitHub
- **THEN** the updater puts the saved environment back, the configurator of the version installed before starts, and the message bar says the update failed with the reason, the version still installed, and that `update.log` has the details

#### Scenario: Newer version already installed
- **WHEN** a configurator 0.122.0 started before the tools were reinstalled as 0.128.3 from the command line, and it updates to 0.124.0
- **THEN** nothing is installed or removed, 0.128.3 stays installed, the configurator 0.128.3 starts in the same tab, and the message says "Already on 0.128.3"

### Requirement: Update when I quit

Update SHALL be refused, with the reason, while the configurator has unsaved changes, an open online connection or local bus, a running trace or simulator, or a running device job. The user SHALL then be able to choose "Update when I quit", which runs the same update after Quit or after the last tab closes, instead of a plain stop.

#### Scenario: Unsaved changes
- **WHEN** Update is pressed with unsaved changes
- **THEN** nothing stops, the page names the unsaved changes and offers "Update when I quit"

#### Scenario: Updates on quit
- **WHEN** the user chose "Update when I quit" and then presses Quit
- **THEN** the update runs as from the Update button, and the next start of the configurator shows the result

### Requirement: Update from the command line

`canworks-config --update` SHALL print the installed and newest versions. When a newer one exists and the tools are a uv tool install, it SHALL update them after a yes (or at once with `--yes`). When a configurator runs, it SHALL ask that configurator to update, which applies the same guard. Otherwise it SHALL run the updater without starting a configurator: in the terminal on macOS and Linux, in the background on Windows. It SHALL exit non-zero when it cannot update.

#### Scenario: Headless update
- **WHEN** `canworks-config --update --yes` runs on a Linux machine with no configurator running and a newer release exists
- **THEN** it prints the uv progress, `canworks-deploy --version` then prints the new version, and it exits 0

#### Scenario: Already newest
- **WHEN** `canworks-config --update` runs and the newest release is installed
- **THEN** it prints that the newest version is installed and exits 0 without asking

### Requirement: Restart into the installed version

When the installed tools are newer than the running configurator (they were reinstalled while it ran), the page SHALL say "<version> is installed; restart to use it" with a Restart action instead of an update offer. Restart SHALL apply the update guard and bring the open tab back in the installed version, without installing anything.

#### Scenario: Reinstalled while running
- **WHEN** the configurator 0.122.0 runs and the tools are reinstalled as 0.128.3 from the command line
- **THEN** the page shows "0.128.3 is installed; restart to use it", and Restart brings the same tab back in the configurator 0.128.3 with nothing installed
