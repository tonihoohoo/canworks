## ADDED Requirements

### Requirement: Failed downloads fail the job
Every install job and the `--ssh` forms of `install-bridge.sh` and `install-bridge.ps1` SHALL download their script to a file before running it. A failed download SHALL end the job with a non-zero exit and "could not download SCRIPT VERSION", and the page SHALL show it failed.

#### Scenario: Tag gone
- **WHEN** the user runs Uninstall on a device whose bridge version's release no longer exists
- **THEN** the job ends failed with the download message and the page does not record a finished uninstall

### Requirement: Update keeps the link and discovery settings
The options of Update and of a reinstall SHALL default to the device's current state: the remote link only when installed, serving the instance it serves now, and discovery only when the device advertises now.

#### Scenario: Link turned off
- **WHEN** the user turned the remote link and discovery off and then presses Update
- **THEN** the job installs the new bridge and leaves the link and the advertisement off

### Requirement: Running instance named before a start
When another bridge instance is active on the device, the Start and Update confirmations SHALL name it and offer **Stop A and start B** as the main action and **Start next to A** as the other. A clash of the Modbus listen port, the diagnostics port or a CAN interface SHALL be a warning in the confirmation.

#### Scenario: Same port
- **WHEN** vp2 runs on 127.0.0.1:1502 and the user opens om2, which uses the same port, and presses Start this project's bridge
- **THEN** the confirmation names vp2, warns about port 1502 and offers Stop vp2 and start om2

### Requirement: Job results name their instance
A finished job's text SHALL name the instance the job ran for, whatever project is open.

#### Scenario: Other project opened
- **WHEN** an Update for vp2 finished and the user opens om2's Devices page
- **THEN** the finished job still says the bridge runs vp2's saved config

### Requirement: Jobs and the device list
Removing a device SHALL forget its running job. A probe that shows a job inactive SHALL clear it. The probe SHALL report the last job's exit code as a number.

#### Scenario: Remove during a job
- **WHEN** the user removes a device while its job runs
- **THEN** the jobs panel no longer shows it and Update now of the PC tools is not refused

### Requirement: Current config over every uploaded file
The plan SHALL call the device's config current only when every file the job uploads (the config, EDS and simulation files) matches by SHA-256.

#### Scenario: Edited EDS
- **WHEN** only an EDS next to the config changed since the last start
- **THEN** the page offers Start this project's bridge

### Requirement: Simulated networks and the adapter
The remote CAN adapter row and dialog SHALL ignore networks with `adapter.simulate` true when locking a bit rate, refusing an adapter or showing the master line.

#### Scenario: Simulated network on can0
- **WHEN** this project's bridge runs and its only network is simulated with a kept adapter can0 at 250 kbit/s, and can0 is up at 500 kbit/s
- **THEN** the dialog offers can0 at 500 kbit/s, not locked, without the master line

### Requirement: Devices layout and wording
Below 1000 px the device list SHALL sit above the device details. The sudo password field SHALL have its label above and its hint below. The job log summary SHALL use the right plural, the device header SHALL keep the user name's case, and the Actions menu SHALL read **Uninstall canworks from the device…** and **Forget this device**.

#### Scenario: 800 px
- **WHEN** the Devices page is shown at 800 px
- **THEN** no word in the parts table is split inside and nothing scrolls sideways
