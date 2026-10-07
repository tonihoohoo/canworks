## ADDED Requirements

### Requirement: Send frames from the Trace view
The Trace view SHALL have a Send panel for the picked network with the identifier (hex), extended and remote options, a DLC for remote frames, up to 8 data bytes, and single or cyclic sending with a period and an optional count. It SHALL send through online access with `send_frame` and stop jobs with `send_frame_stop`, list the running cyclic jobs with their sent counts and a Stop for each, and list the last 20 frames sent. A frame selected in the trace SHALL be offered as "Send this frame", filling the panel. When online access has no `allow_changes`, the panel SHALL be disabled and say why. When the plugin refuses a frame because `force` is needed, the configurator SHALL show the plugin's reason in a confirmation and resend with `force` only when the user confirms. Leaving the Trace view or closing the page SHALL stop the page's cyclic jobs.

#### Scenario: Single frame while recording
- **WHEN** a trace is recording and the user sends 0x60A with eight data bytes
- **THEN** the frame appears in the trace as Tx and in the panel's sent list

#### Scenario: Force needs confirmation
- **WHEN** the user sends on 0x205, which is RPDO1 of node 5
- **THEN** a confirmation quotes "0x205 is RPDO1 of node 5" and nothing is sent unless the user confirms

#### Scenario: No changes allowed
- **WHEN** the config's online access has `allow_changes` off
- **THEN** the Send panel is disabled and says that sending needs Allow changes

### Requirement: Detect the bit rate from the Scan page
The Scan the bus page SHALL have a "Detect bit rate" action for the picked network. Before starting it SHALL warn that CANopen on that network stops during the sweep and the nodes boot again afterwards, and ask for confirmation (with `force` when the plugin says a node is OPERATIONAL). While it runs it SHALL show the rate being listened to and the per-rate counts so far; when finished, the verdict and a table of the rates with frame, error frame and identifier counts. On `detected` with a rate different from the network's `adapter.bitrate`, it SHALL offer "Use N kbit/s", which sets the network's bit rate on the page without saving. It SHALL show no such button for `silent`, `ambiguous` or `failed`, and SHALL show the plugin's reason for `failed` and refusals.

#### Scenario: Unknown device's rate
- **WHEN** the tab's bit rate is 500 kbit/s and the sweep finds 250 kbit/s
- **THEN** the page shows `250 kbit/s detected` and a "Use 250 kbit/s" button, and clicking it sets the bit rate field to 250 kbit/s with the page marked unsaved

#### Scenario: Silent bus
- **WHEN** the sweep finds no frames
- **THEN** the page says the bus was silent and suggests powering a device on or resetting it during the sweep
