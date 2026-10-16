## Why

The node page offers settings the node's EDS cannot back, and explains EDS limits in two different looks:

- The **Emergency (EMCY)** section (EMCY code, Error register, EMCY COB-ID) is shown and editable for every node, also when the EDS has no EMCY object 0x1014, so the device sends no emergency messages. The plugin already refuses `emcy_code_location` and `error_register_location` then, but the configurator only finds out at the Check, and `emcy_cob_id` is taken without a word.
- **Watches the master heartbeat** (`heartbeat_consumer`, object 0x1016) can be set to On or Off for a node whose EDS has no 0x1016, so nothing on the device can take the setting.
- The reason a setting cannot be used is amber warning text under LSS ("This device's EDS has no LSS ...") but grey hint text under Configuration check ("The EDS has no 0x1020 ..."), although both say the same kind of thing. Amber reads as "something is wrong" when nothing is.

## What Changes

- **EMCY needs 0x1014.** When the node's EDS has no 0x1014, the EMCY section's three fields and both Suggest buttons are disabled, with one grey line in the section: "The EDS has no EMCY COB-ID (0x1014), so this device sends no emergency messages." The section stays in place (not hidden) so the user sees why. The plugin and the Check reject `emcy_code_location`, `error_register_location` and `emcy_cob_id` on such a node, naming the node, the field and 0x1014 (today only the first two are rejected, and only by the plugin).
- **Heartbeat consumer needs 0x1016.** When the node's EDS has no 0x1016 with a writable sub-index, "Watches the master heartbeat" stays on "EDS default" and is disabled, with the grey reason "The EDS has no consumer heartbeat time (0x1016), so the device cannot watch the master's heartbeat." The plugin and the Check reject `heartbeat_consumer` (true or false) on such a node.
- **One look for EDS limits.** A reason why a control is disabled because of the EDS is grey hint text, the same as the Configuration check hint. Amber is used only when the loaded config still has a setting the EDS cannot back; then the text says so and offers a "Remove ..." link (as LSS already does), and saving is refused until it is removed or the EDS changes. This applies to LSS, Configuration check and store, EMCY and the heartbeat consumer.
- PC tools minor version bump (0.77.0). A config that sets EMCY or heartbeat consumer fields on a node whose EDS lacks the object is now rejected: a clean cut, the toolkit is not in real use.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-configurator`: EMCY section and heartbeat consumer choice follow the EDS; one style for EDS-limit reasons; LSS reason is grey unless the config still has `lss`.
- `canopen-node-supervision`: EMCY fields and `heartbeat_consumer` need their objects in the node's EDS.

## Impact

- `tools/deploy/canworks/configurator/static/node.js` (`supervisionTab`), `app.js` (`emcyCobField`, the heartbeat consumer `choice`, `lssFields`, `configCheckField`, `storeConfigurationField`), `style.css` if a shared class is added.
- `tools/deploy/canworks/contract.py` (Check messages, same text as the plugin).
- `plugin/src/canopen/eds_check.cpp` (`emcy_cob_id`, `heartbeat_consumer` checks; existing 0x1014 check message reworded).
- Tests: `test_contract.py`, `test_configurator_page.py`, plugin unit tests; config fixtures that set these fields on nodes without the objects.
- README: the node settings section says EMCY and heartbeat consumer settings show only for devices whose EDS has them.
- Kept apart from the "Click highlight and resizable lists" change (row highlight and list resizing), which touches other parts of the page.
