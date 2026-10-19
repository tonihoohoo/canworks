## MODIFIED Requirements

### Requirement: Local access only
The configurator SHALL listen only on the loopback interface and SHALL reject any request that does not carry the random session token it generated at start; the only exception SHALL be the running-instance request of a second start, which needs the instance secret instead. The session cookie's name SHALL include the port in the request's Host, so configurators on different ports keep separate sessions. The page SHALL load no resource from the network. The configurator's own outgoing connections SHALL go only to the runtime host and port the user entered for online access, and only while the user has the online view or scan open.

#### Scenario: Request from another host
- **WHEN** another machine on the LAN connects to the configurator's port
- **THEN** the connection is refused because nothing listens on a non-loopback address

#### Scenario: Request without the token
- **WHEN** a local process sends a save request without the session token
- **THEN** the request is rejected and nothing is written

#### Scenario: Offline editing makes no connection
- **WHEN** the user edits and saves a config without opening the online view or scan
- **THEN** the configurator opens no network connection

#### Scenario: Two configurators in one browser
- **WHEN** one configurator is open at port 9000 and one started with `--new-instance` at port 9001 in the same browser
- **THEN** both pages keep working and neither is logged out by the other

## ADDED Requirements

### Requirement: Quit from the page
Every page of the configurator, the start page included, SHALL have a **Quit** button in the header that stops the configurator. It SHALL always ask first: with unsaved changes offering Save and quit, Quit without saving and Cancel, otherwise Quit and Cancel. With an open adapter connection, send jobs, a trace recording or a PDO test it SHALL say they will stop. After quitting, the tab SHALL show that the configurator has stopped, that the tab can be closed, and how to start it again.

#### Scenario: Quit asks first
- **WHEN** the user presses Quit with nothing unsaved
- **THEN** the configurator asks whether to quit, and Cancel leaves it running

#### Scenario: Quit with unsaved changes
- **WHEN** the user has changed a node and presses Quit
- **THEN** the configurator asks; Save and quit saves and stops it, Cancel leaves everything as it was

#### Scenario: Quit while connected to an adapter
- **WHEN** the user is connected to a USB adapter with a cyclic send job and presses Quit
- **THEN** the dialog says the connection and the send job will stop, and after Quit the adapter is free for other tools

### Requirement: One configurator per user
A running configurator SHALL make itself known to later starts by the same user only, with a secret readable only by that user. A second `canworks-config` SHALL open a new start address of the running configurator in the browser and exit, and with a PATH SHALL ask the running configurator to open that folder, which SHALL ask first when the open config has unsaved changes. `--new-instance` SHALL start a separate configurator. A configurator that no longer runs SHALL NOT stop a new start.

#### Scenario: Started again after closing the tab
- **WHEN** the configurator runs and the user closed its tab, then runs `canworks-config` again
- **THEN** a tab opens on the running configurator with the same open folder, and no second server is started

#### Scenario: Another user on the same PC
- **WHEN** a second user on the same computer runs `canworks-config`
- **THEN** that user gets a configurator of their own and cannot reach the first user's

### Requirement: Closing the last tab stops the configurator
The configurator SHALL stop when its last page is closed: 10 s after the page said it was closing, or 3 minutes after the last page stopped answering (browser crash, sleep), so that a reload does not stop it. Stopping SHALL close every connection as Disconnect does. Closing or reloading a page SHALL always first get the browser's leave-page question (browsers show it only after the user has clicked or typed on the page, and with their own wording). `--keep-running` SHALL keep the configurator running without pages until Quit or Ctrl-C, for scripts and remote use.

#### Scenario: Tab closed
- **WHEN** the user closes the configurator's only tab with nothing unsaved
- **THEN** within 15 s the configurator has stopped, its terminal (if any) shows the prompt again, and its USB adapter is free

#### Scenario: Reload
- **WHEN** the user reloads the page
- **THEN** the configurator keeps running and the page comes back with the same folder and connection

#### Scenario: Two tabs
- **WHEN** two tabs of the configurator are open and the user closes one
- **THEN** the configurator keeps running

#### Scenario: Closing asks first
- **WHEN** the user has worked on the page and closes the tab
- **THEN** the browser asks first whether to leave the page, and Cancel keeps the configurator running

### Requirement: Start without a terminal
`canworks-config` SHALL by default start the configurator detached from the terminal (with no console window on Windows), open the browser and return at once, writing its output to a log file in the configurator's settings folder, kept to 1 MB plus one older file. `--foreground` SHALL keep it in the terminal as before, stopped also by Ctrl-C. It SHALL start in the foreground by itself with `--no-browser` or `--keep-running`, in an SSH session, and on Linux without `DISPLAY` or `WAYLAND_DISPLAY`. A configurator whose first page has not opened within 3 minutes of starting SHALL stop. In every case it SHALL stop when its last tab closes, or by Quit.

#### Scenario: Terminal closed
- **WHEN** the user runs `canworks-config` and closes the terminal
- **THEN** the prompt came back at once, the configurator keeps running and its page keeps working

#### Scenario: Foreground
- **WHEN** the user runs `canworks-config --foreground`
- **THEN** the configurator runs in the terminal, prints its messages there, and Ctrl-C stops it

#### Scenario: Over SSH
- **WHEN** the user runs `canworks-config` in an SSH session
- **THEN** it stays in the terminal, as with `--foreground`

#### Scenario: Background start fails
- **WHEN** the configurator cannot start (for example the folder given cannot be opened)
- **THEN** `canworks-config` prints the reason from the log and exits non-zero

### Requirement: App shortcut
`canworks-config --create-shortcut` SHALL add a shortcut that starts the configurator with no terminal: on Windows a Start menu and a desktop shortcut that run it with `pythonw` (no console window), on macOS an app "canworks configurator" in `~/Applications`, on Linux a `.desktop` entry in the user's applications folder. The shortcut SHALL start the configurator from the installed PC tools, so it keeps working after an update. `--remove-shortcut` SHALL remove what `--create-shortcut` added and nothing else. The one-line PC installers SHALL create the shortcut unless given `--no-shortcut` (`-NoShortcut` on Windows), and their uninstall SHALL remove it.

#### Scenario: Started from the shortcut
- **WHEN** the user double-clicks the shortcut
- **THEN** the browser opens on the configurator's start page and no terminal or console window appears

#### Scenario: Shortcut while running
- **WHEN** the configurator already runs and the user double-clicks the shortcut again
- **THEN** a new tab opens on the running configurator

#### Scenario: Installer
- **WHEN** the user installs the PC tools with the one-line installer
- **THEN** the shortcut is there afterwards, and the installer's uninstall removes it
