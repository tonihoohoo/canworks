## Why

Messages on the PC tool pages look and sit differently from place to place. The message bar is at the top under the header, but the result of Parameters jobs, the Error history and NMT "Locked" notes, the J1939 DM result and the connect panel's error sit at the bottom of their section or dialog. The same severity has up to five looks: a warning is amber text in one section, an amber box in the Machine view, red in the connection bar and the simulation problems list, and plain grey in the simulation banner. Information is grey, grey with a green bar (Frame lab) or muted text. Users have to hunt for what happened and cannot tell a warning from an error at a glance.

## What Changes

- One message bar component for every page, view, section and dialog message, in four kinds: **information**, **done** (success), **warning** and **error**. Each kind has one tint, one left accent bar and one state icon, the same in every place, in light and dark theme.
- One placement rule: a message sits at the **top** of what it is about. Page messages in the message bar under the header; view and section messages directly under the view's or section's heading, before its controls; dialog messages at the top of the dialog body. Nothing below the buttons or at the bottom of a panel.
- Messages inside a dialog stay in the dialog. The connect panel no longer points at "the message at the top" behind it.
- The connection bar and the simulation banner use the same tints: the connection bar is amber for warnings (error passive, slow round trip) and red only for errors; the simulation banner is a warning bar.
- Locked notes (Unlock…), read-only reasons, stale-data notes, "needs a connection" lines, job results and section warnings all move to the component and its top slot.
- The Machine view's notices (switched to Low, no data, no WebGL) use the same bar at the top of the stage.
- Field-level text stays next to its field: hints, a field's error, a table row's own error (Send rows) and an inline read value. The **Problems** panel and the **status bar** stay at the bottom; problem rows use the same icons and tints.
- A test walks every view and dialog and fails when a message is not the component or is not at the top of its section.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-configurator`: message bar look and kinds, where messages go, dialog messages, connection bar tints, simulation banner look.
- `canopen-machine-view`: the view's notices use the message bar at the top of the stage.

## Impact

- `tools/deploy/canworks/configurator/static/`: `app.js` (`banner()`, new `notice()` helper), `style.css`, `icons.js` (info icon), and the views that build their own message elements (`commission.js`, `connection.js`, `nodes.js`, `node.js`, `sim.js`, `trace.js`, `trace_ids.js`, `j1939.js`, `rawcan.js`, `explain.js`, `machine_view.js`, `identity.js`, `tracewin.js`, `transmit.js`).
- Tests: `tools/deploy/tests/test_configurator_page.py` (placement walk, kinds, dialog messages), wording test unchanged.
- Docs: `docs/configurator.md` (message bar, colours and icons legend), README feature line.
- Not affected: the plugin, the config contract, the exported HTML documentation (a document, not a page; its warning lists stay as they are).
- Related changes in flight: `eds-gated-node-settings` (grey hint for EDS limits, amber only for leftover settings) and `row-highlight-and-list-resize`. This change keeps their field-level hints; a leftover-setting warning with its Remove action becomes a section warning bar. Apply after both have merged.
