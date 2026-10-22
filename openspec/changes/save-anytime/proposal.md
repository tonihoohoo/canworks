# Proposal

## Why

The usability hunt of 2026-10-21 (H1, M9, M13) found that the configurator can lose a user's work in normal steps:

- **Save is disabled while Problems has any error** ("Validate before save", "Busy states and the Save button"). Ordinary first steps already make errors. A new config's network with no node is an error ("No nodes yet…"). A node added from an EDS whose heartbeat default (0x1017) is 0 is an error straight away ("has no heartbeat or guarding"). So a user who adds the first node can't save until they find the Supervision tab.
- **New config… writes nothing to disk.** The folder and the target picked in the dialog live only in the page's draft. In the hunt, a new Modbus bridge config with one node, reloaded, came back as "Saved" with target OpenPLC, no nodes, and no folder on disk.
- The problem text uses config keys: `set heartbeat_ms, or "heartbeat_ms": 0 to accept that`. It has no button that fixes it.
- With an empty name, the New config dialog's error replaces the dialog's title and doesn't mark the field.

The errors exist for a good reason: the plugin, the bridge and CODESYS refuse such a config. But refusing to *save* protects nothing: the steps that hand the config over check again. The work in the draft is what is at risk.

## What Changes

- **Save always saves.** Save writes the draft even when Problems has errors. It reads "Save" when dirty, and "Saved, 2 problems" (disabled) when clean with problems. A save with errors shows a message bar: "Saved with 2 errors: the runtime refuses this config until they are fixed". The Allow overlap control stays as it is (it now only matters to the hand-off steps).
- **Hand-off steps check instead.** Everything that gives the config to something that runs it refuses while the saved config has errors, says why in one line, and links to Problems:
  - Build into CODESYS project and Download for CODESYS;
  - Devices → install or update the bridge config;
  - the `canworks-deploy` editor hook (it already runs the checks).

  Exports (DCF, DBC, documentation) keep their own rules.
- **Create writes the folder.** New config… creates the folder and writes the target's empty config on Create, before the page opens it. An editor project's config is written to `canworks/` on Create too. A reload then shows the new config with its target.
- **An empty network is not an error.** A CANopen master network with no nodes shows the empty state in the tree and on the Bus page ("No nodes yet: Add node…, or find devices in Commission"). In Problems it is one **warning**, not an error. The hand-off steps still refuse it.
- **A new node starts without problems.** Adding a node whose EDS heartbeat default is 0:
  - with a writable 0x1017, it gets `heartbeat_ms: 1000` (shown on Supervision as "set when the node was added");
  - else, when the EDS supports node guarding, it gets guarding at 1000 ms with life time factor 3;
  - else, the supervision problem stays.
- **Problems with a quick fix.** A problem can carry actions. The supervision problem offers **Use heartbeat 1000 ms** (or **Use guarding** when that is all the EDS offers) and **Accept no supervision** (writes `heartbeat_ms: 0`). Its text names fields in UI words: "Node 2 dio16 has no heartbeat or guarding, so its loss would never be detected. Set the heartbeat period on Supervision." Each quick fix is one undo step.
- **New config dialog errors** show under the field they concern, which is marked and focused. The dialog's title stays.
- PC tools minor version bump; README and docs/configurator.md (Save and problems).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-configurator`: "Validate before save" (save with errors, hand-off steps refuse), "Busy states and the Save button" (labels), "Target of a new config" (Create writes the folder). New requirements: "Hand-off steps need a config without errors", "Empty network is a warning", "Supervision of a new node", "Quick fixes in Problems", "Errors in the New config dialog".

## Impact

- `tools/deploy/canworks/configurator/server.py` (save without the error refusal, `new_config` writes the empty config), `static/app.js` (Save button states, empty-network warning, problem actions, New config dialog), `static/target.js` (Build/Download refuse with errors), `static/devices.js` (install/bridge config refuse with errors), `contract.py` (supervision message wording in UI words for the configurator; the CLI text may stay).
- Tests: page tests for save with errors, Create on disk plus reload, new node gets heartbeat, quick fixes with undo, hand-off refusals; update the tests that expect a disabled Save with errors.
- No plugin, bridge or CODESYS export change. No hardware test.
