# Proposal

## Why

A CODESYS project in the configurator still showed a **PLC location** column in a node's PDO table, with `%IW100` in one entry and, under it, the check's raw text: `C:\Users\…\canworks.json: networks[0].nodes[0].tx_pdos[0].entries[1].iec_location: 'iec_location' is not used by CODESYS: …`, a "not used by CODESYS" tag and Remove. Toni's ask: by default show only the fields that matter for the project's target.

The target pass from `add-codesys-target` (relevance table `targets.py ROWS`, `target.js applyTarget()`) already hides an unused field while it is empty. A field that still has a value stays in place, marked. One leftover is enough to bring back a whole column, a tab or a fieldset, and every leftover adds a warning to the tab badges. A survey of every page for all three targets (OpenPLC, Modbus bridge, CODESYS; method and list in design.md) found three kinds of gap:

1. **Leftover values bring the fields back.** Examples: the PDO table's PLC location column, a TPDO's receive timeout fields, the node status locations on Supervision, the adapter and bus diagnostics fields on the Bus page, a node's Simulation tab when `simulate` is left over, and "4 warnings" badges on tabs.
2. **Text written for OpenPLC shows on every target.** Examples: "The plugin is the network's master", "The interface on the PLC (the Pi)", "Plugin sets up the link", "Bus-off events since the PLC started, also those shorter than a scan", "communication objects the plugin sets", "Each signal gets a free PLC location", the editor-project address scan line, and the Variable declarations page (written for an OpenPLC program) on bridge projects.
3. **On Windows every check message next to a field shows the config's file path.** `readable()` strips `^[^:]*canworks\.json: `, which cannot get past the `:` of a drive letter. The photo shows this. It breaks the existing requirement "Readable problem messages" for all messages, not only target ones.

Usability first: a CODESYS user should see a CODESYS configurator, and a bridge user a bridge configurator.

## What Changes

- **Hidden means hidden, set or not.** With the default view, every field, column, choice option, fieldset, tab and tree entry the target does not use is hidden even when the config still has a value for it. Values left over (from **Switch, keep them**, a hand-edited file or an older config) are not lost and do not clutter the page:
  - a **"Not used by CODESYS"** bar at the top of the page or tab that holds them, folded by default: "2 settings here are not used by CODESYS" with **Remove all** and **Show**; unfolded it lists each one in words ("TPDO 1, Position: PLC location %IW100") with its own Remove;
  - in Problems, **one** grouped warning per config, "5 settings are not used by CODESYS", with **Remove all**; unfolding it lists them, and clicking one opens its page with the bar unfolded;
  - tab and tree badges no longer count these warnings.
- **Show every field.** A View menu item, **Show fields the target does not use** (off by default, remembered on this PC), shows all hidden fields dimmed and tagged "not used by <target>", still editable. This is today's marked view, for someone preparing a target switch. While it is on, the header's target badge reads "· CODESYS · all fields". The bar's **Show** turns it on.
- **Target wording.** Hints, labels and page texts that differ per target get a variant per target from one place, so the bridge and CODESYS never mention the plugin, the Pi, the PLC scan or PLC locations where they do not apply. The editor-project address scan line follows `ui:editor_project`. The Variable declarations page becomes OpenPLC only, because the bridge page already has **Export ST variables** for a PLC that is a Modbus client.
- **A guard test.** For each target, a browser test opens every page and tab of a config where every setting is set. It asserts that no field outside the target's table rows is visible, and that no visible text uses another target's words (word list per target, with the target choice's own help left out).
- **Windows paths in check messages** are stripped like POSIX paths, so no message next to a field or in Problems shows the config's path.
- The command line `check` keeps one warning per unused value (CLI wording unchanged). The `--codesys-import` plan's `not_carried` list is unchanged.
- PC tools minor version bump.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-configurator`: "Only what the target uses is shown" (set values hidden too, the per-page bar, the grouped problem, Show every field, wording per target, Declarations OpenPLC only), "Variable names of PDO entries" (no Location column for a target without locations, even with a leftover), "Readable problem messages" (Windows path scenario). New requirements: "Settings the target does not use on the page", "One problem for the settings the target does not use" and "Show fields the target does not use".

## Impact

- `tools/deploy/canworks/configurator/static/target.js` (`applyTarget` hides set values; the bar; the View toggle; `targetText()` for wording), `app.js` (PDO table column rule, `readable()` drive letters, Problems grouping, badge counts, wording call sites), `node.js` (Simulation and CiA 402 tabs ignore leftovers), `tree.js`, `shell.js` (View menu item, Declarations), `style.css` (bar, dimmed fields).
- `tools/deploy/canworks/targets.py`: `ui:declarations` OpenPLC only; one wording table next to `ROWS`, served with it.
- Tests: page tests per target (hidden leftovers, bar Remove all and Show, grouped problem, toggle remembered, guard sweep), unit test for `readable()` with `C:\…` paths; `test_configurator_codesys_page.py` "Leftover value" changes from "marked" to "listed in the bar".
- README and docs/configurator.md: target section mentions the bar and the View toggle.
- No runtime plugin, bridge or CODESYS export change. No hardware test needed. A Windows desktop look (CODESYS project with leftovers) is a hand check.
