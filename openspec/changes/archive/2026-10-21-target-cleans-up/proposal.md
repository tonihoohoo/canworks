# Proposal

## Why

After `target-relevant-fields` (PR #186), Toni checked it on Windows: "These are ok, but why ask anything? Configurator should work according to target by default." Values the target does not use are still the user's job. They show up as a bar on the page ("N settings here are not used by CODESYS", Remove all / Show), as a warning in Problems, and as a Remove or Keep question when the target is switched. A Settings toggle also brings them back. All of this is asking the user to manage something the configurator already knows has no effect.

The same check found odd text on a CODESYS node's Supervision tab (photo, "Weird message"):

- The **Emergency (EMCY)** section is back on CODESYS. It says "The EDS has no EMCY COB-ID (0x1014), so this device sends no emergency messages" and still shows an EMCY COB-ID choice. CODESYS uses no EMCY setting from canworks, so the section should not be there. Cause: #186 now keeps a section while any control is visible, and the COB-ID mode select has no setting path.
- The **Heartbeat watch** block reads "Heartbeat watchNodes whose heartbeat…" and "…heartbeat timeout.The EDS has no consumer…". The heading and the hint run together in one narrow grid cell, because the block's spans are inline and the block takes a single column. For a device whose EDS has no 0x1016, the whole block is only an explanation of something the device cannot do.
- An EDS without 0x1014 gets an EMCY section with disabled controls and a sentence saying the device sends none. That is a set of controls the user can never use.

## What Changes

- **The configurator cleans up by itself.** Values the project's target does not use are never shown and never asked about:
  - **Save leaves them out.** The saved file holds only what the target uses. The save message says so in one clause ("3 settings CODESYS does not use were left out"). The draft is not marked unsaved just for opening such a file.
  - **Switching the target asks nothing.** Picking another target switches at once, in one undo step. It drops what the new target does not use, writes CODESYS variable names, and repacks locations (per type for OpenPLC, packed for Modbus). A message names what happened and that Undo brings it back. The dialog and its Remove/Keep and repack choices go.
  - **No bar, no grouped problem, no Settings toggle.** The per-page "not used by …" bar, the grouped Problems warning, the "Show fields the target does not use" setting (`show_all_fields` in `ui.json`) and the "· all fields" mark are removed.
  - Network kinds a target cannot run (a slave, J1939 or plain CAN network in a CODESYS project) cannot be dropped. They keep their existing one-line note on the network's page.
  - The command-line check keeps warning per value, so a file edited by hand is still reported there.
- **Supervision tab:**
  - No EMCY section on CODESYS. The section is drawn only when the target uses EMCY settings.
  - Heartbeat watch is a block of its own across the grid, with the heading and hint on their own lines. It is not drawn when the node's EDS has no writable 0x1016 and the node watches nobody.
  - An EDS without 0x1014 gets one line in place of the EMCY controls: "The EDS has no EMCY COB-ID (0x1014): this device sends no emergency messages." There are no disabled controls. A leftover EMCY setting still gets its warning and Remove, since saving it is refused.
- PC tools minor version bump.

## Capabilities

### Modified Capabilities

- `canopen-configurator`:
  - "Only what the target uses is shown": no listing of leftovers, the EMCY section follows the target.
  - "Switching the target": no dialog.
  - "Variable names of PDO entries": no toggle.
  - "EMCY section follows the EDS": one line, no disabled controls.
  - "Heartbeat consumer choice follows the EDS": no watch block without 0x1016.
  - Removed: "Settings the target does not use on the page", "One problem for the settings the target does not use", "Show fields the target does not use".
  - Added: "Settings the target does not use are left out on save".

## Impact

- `configurator/static/target.js`: drop the bar, the grouped problem, `setShowAll` and the switch dialog. `switchTarget` posts directly.
- `app.js`: save message, Problems no longer groups.
- `node.js`: EMCY section by target, one-line EDS limit.
- `links.js`, `style.css`: Heartbeat watch layout and hiding.
- `shell.js`, `index.html`: Settings toggle removed.
- `configurator/server.py`: `/api/save` removes unused values with `targets.remove` and returns the count. `/api/switch_target` always removes. `show_all_fields` leaves `UI_SETTINGS`.
- Tests: CODESYS and bridge page tests (no bar, no dialog, save drops values), the target sweep (no toggle pass, EMCY not on CODESYS, no glued text), server tests for save and switch, UI defaults.
- README and docs/configurator.md: switching and saving drop what the target does not use.
- No runtime, bridge or CODESYS export change. Windows hand check: open the photo's CODESYS config, Supervision tab, save.
