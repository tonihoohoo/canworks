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
Every page of the configurator, the start page included, SHALL have a **Quit** button in the header that stops the configurator. With unsaved changes it SHALL ask first, offering Save and quit, Quit without saving and Cancel. With an open adapter connection, send jobs, a trace recording or a PDO test it SHALL say they will stop. After quitting, the tab SHALL show that the configurator has stopped, that the tab can be closed, and how to start it again.

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

### Requirement: Start without a terminal
`canworks-config --background` SHALL start the configurator detached from the terminal (with no console window on Windows), open the browser and return at once, writing its output to a log file in the configurator's settings folder, kept to 1 MB plus one older file. A configurator started this way SHALL stop by itself when no page of it has been open for 10 minutes and no trace recording, send job or PDO test runs. A configurator started in a terminal SHALL NOT stop by itself.

#### Scenario: Terminal closed
- **WHEN** the user runs `canworks-config --background` and closes the terminal
- **THEN** the configurator keeps running and its page keeps working

#### Scenario: Forgotten in the background
- **WHEN** the user closes the last tab of a background configurator and nothing records or sends
- **THEN** the configurator stops within 11 minutes and its adapter connection is closed

#### Scenario: Background start fails
- **WHEN** the background configurator cannot start (for example the folder given cannot be opened)
- **THEN** `canworks-config --background` prints the reason from the log and exits non-zero

### Requirement: Adapter freed when no page is open
When no page of the configurator is open, its USB adapter connection SHALL close as Disconnect does, stopping the scan, PDO test, SYNC, send jobs and trace recording on it: 10 s after the last page was closed, or 3 minutes after the last page stopped answering (browser crash, sleep). A reload SHALL NOT close it. The next page SHALL say in the message bar that the adapter connection was closed because no configurator page was open.

#### Scenario: Tab closed while connected
- **WHEN** the user is connected to gs_usb:0 and closes the configurator's only tab
- **THEN** within 15 s the adapter is free, and `canworks-diag --adapter gs_usb:0` can open it while the configurator still runs

#### Scenario: Reload keeps the connection
- **WHEN** the user reloads the page while connected to an adapter
- **THEN** the connection stays open and the page shows it connected

#### Scenario: Two tabs
- **WHEN** two tabs of the configurator are open and the user closes one
- **THEN** the adapter connection stays open

### Requirement: New start address from the terminal
While the configurator runs in a terminal, pressing Enter SHALL print a new one-time start address and open it when the configurator opens browsers. Earlier sessions SHALL keep working, and at most 16 unused addresses SHALL be kept, the oldest dropped first.

#### Scenario: Enter after closing the tab
- **WHEN** the user closes the tab and presses Enter in the configurator's terminal
- **THEN** a new address opens the page with the same open folder, and the first address stays refused
