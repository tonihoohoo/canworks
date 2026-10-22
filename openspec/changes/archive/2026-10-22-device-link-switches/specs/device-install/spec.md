## ADDED Requirements

### Requirement: Remote link and discovery switches
The device page SHALL give the remote link and the local-network advertisement their own actions, with and without a config open, when the canworks plugin or the bridge is installed on the device. The **Remote link** row SHALL offer **Turn on…** when the link is not installed, **Turn off…** when it is, and **Start** when it is installed but not running, and SHALL say which config it serves ("serves the PLC" for the plugin's config, "serves the bridge NAME" for a bridge instance). A row **Found on the local network** SHALL show whether the advertisement is installed, with **Turn on…** or **Turn off…**. Each action SHALL run as an install job with the release's `install-link.sh` at the newest release X. Turning the link on SHALL serve the plugin's config when the plugin is installed, else the open bridge project's instance, else the only bridge instance on the device; with several instances and none of these, the dialog SHALL ask which instance. Turning the link off SHALL keep the link's key and paired PCs, and SHALL leave the advertisement (without the link ID) when discovery is on. In a CODESYS project, and on a device with neither the plugin nor the bridge, both rows SHALL have no action.

#### Scenario: Turn the link off and on again
- **WHEN** a device's link serves the PLC and one PC is paired, and the user turns the link off and then on
- **THEN** the link row reads not installed after the first job and "running · serves the PLC" after the second, the link ID is the same, and the PC is still paired

#### Scenario: Discovery off
- **WHEN** the user turns **Found on the local network** off on a device with the link running
- **THEN** the Avahi file is removed, the link keeps running, and the row offers **Turn on…**

#### Scenario: Two bridge instances, no config
- **WHEN** a device has no plugin and two bridge instances `packer` and `line2`, no config is open, and the user turns the link on
- **THEN** the dialog asks which instance the link serves, and the job serves the picked one

#### Scenario: Nothing installed
- **WHEN** a device has neither the plugin nor the bridge
- **THEN** the Remote link and Found on the local network rows have no action
