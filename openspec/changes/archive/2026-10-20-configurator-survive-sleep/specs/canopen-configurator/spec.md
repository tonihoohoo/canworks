## MODIFIED Requirements

### Requirement: Closing the last tab stops the configurator
The configurator SHALL stop when its last page is closed: 10 s after the page said it was closing, so that a reload does not stop it. A page that stopped answering without saying it was closing (browser crash, a locked screen, sleep) SHALL count as closed only when its last answer said it had no unsaved changes and then only 60 minutes after that answer; a page whose last answer said it had unsaved changes SHALL NOT count as closed until it says it is closing, the configurator is quit, or it is stopped by a signal. Time in which the configurator itself did not run (the computer slept) SHALL NOT count toward the 60 minutes on any operating system. When it stops by itself, its log SHALL say why, with different words for a closed page (`its last page was closed`) and a silent one (`its last page sent no heartbeat for 60 minutes`). Stopping SHALL close every connection as Disconnect does. Closing or reloading a page SHALL always first get the browser's leave-page question (browsers show it only after the user has clicked or typed on the page, and with their own wording). `--keep-running` SHALL keep the configurator running without pages until Quit or Ctrl-C, for scripts and remote use.

#### Scenario: Tab closed
- **WHEN** the user closes the configurator's only tab with nothing unsaved
- **THEN** within 15 s the configurator has stopped, its terminal (if any) shows the prompt again, its USB adapter is free, and its log says its last page was closed

#### Scenario: Browser quit
- **WHEN** the user quits the browser while it shows the configurator's only tab with nothing unsaved
- **THEN** within 15 s the configurator has stopped

#### Scenario: Reload
- **WHEN** the user reloads the page
- **THEN** the configurator keeps running and the page comes back with the same folder and connection

#### Scenario: Two tabs
- **WHEN** two tabs of the configurator are open and the user closes one
- **THEN** the configurator keeps running

#### Scenario: Closing asks first
- **WHEN** the user has worked on the page and closes the tab
- **THEN** the browser asks first whether to leave the page, and Cancel keeps the configurator running

#### Scenario: Screen locked
- **WHEN** the configurator's only tab is open in a browser that stops its timers while the screen is locked, and the screen stays locked for 20 minutes
- **THEN** after unlocking, the page works without a reload and Save works

#### Scenario: Unsaved changes and a silent page
- **WHEN** the page has unsaved changes and sends no heartbeat for two hours
- **THEN** the configurator keeps running, and the page can save when it answers again

#### Scenario: Browser crashed
- **WHEN** the browser stops without the page saying it is closing and the page had nothing unsaved
- **THEN** the configurator stops 60 minutes after the page's last heartbeat, and its log says its last page sent no heartbeat for 60 minutes

#### Scenario: Computer slept
- **WHEN** the computer sleeps for two hours with the configurator's tab open and nothing unsaved
- **THEN** after waking, the configurator is still running and the page works without a reload

## ADDED Requirements

### Requirement: Page of a stopped configurator
When a page of the configurator becomes visible again, comes back from the browser's back/forward cache or gets focus, it SHALL ask the configurator at once whether it runs. When the configurator does not answer two asks in a row, 2 s apart, the page SHALL replace its content with a notice that canworks-config is not running any more and how to start it again (the app shortcut, or `canworks-config` in a terminal, which opens a new tab). A single unanswered ask SHALL NOT show the notice. With unsaved changes, the notice SHALL say that they could not be saved, SHALL offer **Download canworks.json** with the page's unsaved config, and SHALL name what the download does not hold (EDS and notes files imported since the last save, unsaved simulation edits). After the notice nothing on the page SHALL ask the configurator any more.

#### Scenario: Configurator gone while the page was hidden
- **WHEN** the configurator was stopped from a terminal while its tab was in the background, and the user returns to the tab
- **THEN** within 5 s the tab says canworks-config is not running any more and how to start it again, instead of showing a working page whose buttons fail

#### Scenario: Unsaved changes kept as a file
- **WHEN** the configurator stopped while its page had an unsaved node change, and the user presses Download canworks.json on the notice
- **THEN** the browser saves a canworks.json that holds the change, and opening it in a new configurator shows the node as edited

### Requirement: Words for a remote adapter connection
On a connection to an adapter on another machine, the configurator SHALL NOT call the connection a USB adapter connection, and SHALL name the host: the lock texts SHALL say changes are off for the connection to the adapter on HOST, and the trace SHALL report frames the adapter machine's kernel dropped as dropped by the adapter machine's kernel, not the PLC's.

#### Scenario: Locked remote adapter
- **WHEN** the user is connected read-only to an adapter on another machine and presses a write control
- **THEN** the message says changes are off for the connection to the adapter on that host, and does not say USB adapter

#### Scenario: Drops in a remote trace
- **WHEN** a trace through an adapter on another machine reports kernel drops
- **THEN** the trace summary says they were dropped by the adapter machine's kernel and names the host, and does not mention a PLC
