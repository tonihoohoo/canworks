## MODIFIED Requirements

### Requirement: Start without a terminal
`canworks-config` SHALL by default start the configurator detached from the terminal (with no console window on Windows), print its start address, ask the browser to open it and return as soon as the browser was asked (without waiting for the page to load), writing its output to a log file in the configurator's settings folder, kept to 1 MB plus one older file. `--foreground` SHALL keep it in the terminal as before, stopped also by Ctrl-C. It SHALL start in the foreground by itself with `--no-browser` or `--keep-running`, in an SSH session, and on Linux without `DISPLAY` or `WAYLAND_DISPLAY`. When no page has opened 15 s after the browser was asked to open it, the background configurator SHALL write its start address to the log and, when it was started from the app shortcut, show it in a message window (Windows message box, macOS dialog, Linux desktop dialog or notification when one is available) from which the address can be copied. A configurator whose first page has not opened within 10 minutes of starting SHALL stop. In every case it SHALL stop when its last tab closes, or by Quit.

#### Scenario: Terminal closed
- **WHEN** the user runs `canworks-config` and closes the terminal
- **THEN** the prompt came back at once, the configurator keeps running and its page keeps working

#### Scenario: Foreground
- **WHEN** the user runs `canworks-config --foreground`
- **THEN** the configurator runs in the terminal, prints its messages there, and Ctrl-C stops it

#### Scenario: Over SSH
- **WHEN** the user runs `canworks-config` in an SSH session
- **THEN** it stays in the terminal, as with `--foreground`

#### Scenario: Browser does not open from the shortcut
- **WHEN** the user starts the configurator from the shortcut and no browser opens
- **THEN** after about 15 s a message window shows the start address to copy into a browser, and the configurator waits up to 10 minutes for it

#### Scenario: Browser does not open from a terminal
- **WHEN** the user runs `canworks-config` and the browser does not open
- **THEN** the terminal already shows the start address, the prompt is back, and no message window appears

#### Scenario: Prompt back before the page loads
- **WHEN** the user runs `canworks-config` and the browser is slow to load the page
- **THEN** the prompt comes back once the browser was asked, without waiting for the page

#### Scenario: Background start fails
- **WHEN** the configurator cannot start (for example the folder given cannot be opened)
- **THEN** `canworks-config` prints the reason from the log and exits non-zero

### Requirement: App shortcut
`canworks-config --create-shortcut` SHALL add a shortcut that starts the configurator with no terminal: on Windows a Start menu and a desktop shortcut that run it with `pythonw` (no console window) and `--from-shortcut`, on macOS an app "canworks configurator" in `~/Applications`, on Linux a `.desktop` entry in the user's applications folder. The shortcut SHALL start the configurator from the installed PC tools, so it keeps working after an update. Started from the shortcut (`--from-shortcut`), the process SHALL itself become the background configurator when none runs, and otherwise open a tab of the running one and exit; it SHALL NOT start a second Python process. Writing the Windows shortcuts SHALL NOT use `-ExecutionPolicy Bypass`. `--remove-shortcut` SHALL remove what `--create-shortcut` added and nothing else. The one-line PC installers SHALL create the shortcut unless given `--no-shortcut` (`-NoShortcut` on Windows), and their uninstall SHALL remove it.

#### Scenario: Started from the shortcut
- **WHEN** the user double-clicks the shortcut
- **THEN** the browser opens on the configurator's start page and no terminal or console window appears

#### Scenario: One process from the shortcut
- **WHEN** the user double-clicks the shortcut and no configurator runs
- **THEN** the process the shortcut started serves the page, and no further Python process is started for it

#### Scenario: Shortcut while running
- **WHEN** the configurator already runs and the user double-clicks the shortcut again
- **THEN** a new tab opens on the running configurator

#### Scenario: Installer
- **WHEN** the user installs the PC tools with the one-line installer
- **THEN** the shortcut is there afterwards, and the installer's uninstall removes it

## ADDED Requirements

### Requirement: Start timing in the log
Each start of the configurator SHALL write one line to its log with the time, in milliseconds from the moment the start was launched (the shortcut or `canworks-config`), at which Python was running, the configurator listened, the browser was asked and the first page loaded, and whether it was started from the shortcut or a terminal. A start whose page does not load SHALL log the line without the page time.

#### Scenario: Normal start
- **WHEN** the user starts the configurator from the shortcut and the page opens
- **THEN** `configurator.log` has one line like `start timing: python 140 ms, listening 420 ms, browser asked 450 ms, page 1310 ms (from shortcut)`

### Requirement: Light starter
The `canworks-config` command SHALL parse its arguments, find a running configurator and start or hand over without importing the configurator's server module or the diagnostics and config validation modules; only a process that serves pages SHALL import them. A unit test in CI SHALL import the entry module in a fresh interpreter and fail when the server or diagnostics module was imported.

#### Scenario: Starter import
- **WHEN** a fresh Python process imports the `canworks-config` entry module
- **THEN** neither `canworks.configurator.server` nor `canworks.diag` is in `sys.modules`
