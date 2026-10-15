## ADDED Requirements

### Requirement: Saved config compared like the deploy tool writes it
The Commission workspace SHALL compare the runtime's config fingerprint with both the saved `canworks.json` and the `conf/canworks.json` the deploy tool and the editor hook write from it, with every node's and every slave's EDS path rewritten as they do. Right after an upload of the saved config, the workspace SHALL NOT say that the runtime runs a different configuration, also when the config has a slave network.

#### Scenario: Gateway config uploaded
- **WHEN** the virtual plant (a slave network `cell` with its own EDS) is uploaded with `canworks-deploy` and the configurator connects to that runtime
- **THEN** the Commission workspace shows no "different configuration" note

### Requirement: Connect panel without empty parts
The connect panel SHALL show nothing in place of the recent connections when there are none, and nothing in place of the runtime and simulator choice on a USB adapter.

#### Scenario: First connection on a PC
- **WHEN** a PC that has never connected opens the connect panel in Commission a device
- **THEN** the panel starts with the adapter form, and no stray text such as "null" appears

### Requirement: Settings on this PC saved while another program reads them
Saving the configurator's settings files on this PC (`online.json`, `ui.json`, `recent.json`, notes files) SHALL try the final rename again for about a second while Windows refuses it because another process has the file open, such as a second configurator. When it still fails, the temporary file SHALL be removed and the error shown as before.

#### Scenario: Two configurators on Windows
- **WHEN** two configurators run on one Windows PC and one connects to an adapter while the other reads `online.json`
- **THEN** the connection is saved without an "access is denied" message, and no `.tmp` file is left in the settings folder

### Requirement: Quick reboots in the Commission log
The Commission log SHALL add "Booted" for a node whenever the runtime's boot count of that node (`boots`) goes up, also when the node's state and boot result did not change between two status answers.

#### Scenario: Reset node from the Status tab
- **WHEN** the user resets node 6 from its Status tab and the master boots it again before the next status answer
- **THEN** the log has the NMT reset and then "Booted" for node 6
