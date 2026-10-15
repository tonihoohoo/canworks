## Why

This is the last of five changes in the configurator's UI overhaul (research note of 2026-10-15, kept outside the repository). The first four move things to the right place: workspaces and the connection bar (`ui-shell-and-connection`), the network tree and node tabs (`network-tree-and-node-tabs`), the Commission workspace (`commission-workspace`) and the trace workspace (`trace-workspace`). This one makes what is on screen quick to read and checks the whole app the way a user works with it.

Today:

- **Colour has no single meaning.** Green, amber and red are used for NMT states, problems, the simulation banner, changed values, the round trip and the frame inspector, each picked on its own. Amber marks both "simulated" and "warning". Operational nodes are green text, so a healthy network is a screen full of colour and a fault does not stand out.
- **Colour is often the only cue.** The online node list shows its state as coloured text; the problem count is red text. Nothing has a shape that survives a colour-blind user, a grey-scale printout or the operating system's high contrast mode.
- **Loose density.** Tables use form spacing, numbers are left-aligned in proportional type, and IDs and data bytes are not in a fixed-width font, so columns of COB-IDs and values are hard to scan.
- **Uneven wording.** The same thing has several names ("bit rate", "bitrate", "baud"; "node ID", "Node-ID"), some buttons are nouns, some messages start with "Error:" and some explain nothing about what to do next.
- **Disabled controls rarely say why.** The CiA 402 switch does; most others do not.
- **The tests check pages, not tasks.** The browser tests open each view and audit it, and one keyboard walk covers the config pages. No test does a whole job, such as connecting and recording a trace, with the keyboard only, and none does it in the dark theme.

The tools in the research handle this the same way: state as a coloured icon with its own shape on the device tree, neutral grey for normal (ISA-101 "high performance HMI"), dense tables with fixed-width IDs, and one status vocabulary everywhere.

## What Changes

- **State colours.** One set of colour tokens for both themes: neutral greys plus four state colours (OK, in progress, warning, error) and a neutral "off". Every place that shows a state uses them; nothing else does. Normal is grey: rows and text stay neutral when all is well, and only the state icon of a healthy node carries colour. All state colours meet 4.5:1 against their background in both themes.
- **State icons.** A small icon set where each state has its own shape as well as its colour: operational (filled circle), pre-operational (half circle), stopped (square), error or missing (cross), unknown or absent (hollow circle), warning (triangle), and a diagnosis flag (pending or cleared). Simulated nodes get a dashed outline. Every icon has a text name for assistive technology and a tooltip, and keeps its shape in forced-colours (high contrast) mode. The same icons are used on the network tree, the Nodes table, node tabs, the connection bar, problems, the message bar and the trace.
- **Density.** Data tables (nodes, PDO entries, startup SDO writes, SDO variables, object dictionary, trace, links, gateway routes, CAN messages) use compact rows of 28 to 32 px, right-aligned numbers with even digit widths, and a fixed-width font for IDs, COB-IDs, indexes, data bytes and PLC locations. Long tables keep their header row in view. One spacing scale replaces ad hoc margins. Controls stay at least 24 px tall.
- **Wording pass.** One word list (`docs/wording.md`) for the page: the preferred term for each concept, sentence-case labels, verbs on buttons, "…" on buttons that open a dialog, units with a space ("500 kbit/s", "100 ms"), and messages that say what happened and what to do next, with no "Error:" prefix and no exclamation marks. Every label, tooltip, empty state and message on the page is brought in line, and a test fails on terms the list rules out.
- **Disabled controls say why.** Every disabled control on the page has a reason the user can read (tooltip and accessible description), such as "Needs a connection with changes allowed" or "This EDS has no 0x6040/0x6041". A test fails on a disabled control without one.
- **Task tests, keyboard only, both themes.** Five end-to-end browser tests that do a user's job with the keyboard alone, each in the Light and Dark themes:
  1. connect to an adapter;
  2. scan the bus;
  3. add a found device to a config;
  4. map a PDO entry and save;
  5. record a trace and save it.

  Each step is audited with axe-core and checks that focus is visible. One extra run of the tree and the Nodes table in forced-colours mode checks that state icons keep their shapes.
- **Legend.** A **Colours and icons** entry in the settings menu opens a short legend of the state icons, and the docs show the same legend.

No file format, server protocol or CLI changes.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-configurator`: new requirements for state colours (grey is normal, contrast), state icons (shapes, diagnosis flag, simulated mark, assistive technology and high contrast), the legend, compact tables and ID format, the word list, empty states and its test, reasons on disabled controls, keyboard-only task tests with per-step checks, and a high contrast check; the accessibility check in the browser tests also covers state icons.

## Impact

- Configurator page: `tools/deploy/canworks/configurator/static/`:
  - `style.css` (tokens, state classes, density, table styles, forced-colours rules) and `rawcan.css`;
  - `index.html` (icon sprite, legend);
  - a small `icons.js` module that renders a state icon with its name;
  - every view's labels, tooltips and messages (`app.js` and the modules split out by the earlier changes, `commission.js`, `trace.js`, `sim.js`, `explain.js`, `links.js`, `bridge.js`, `j1939.js`, `rawcan.js`);
  - hard-coded state colours in `trace.js` and `explain.js` move to tokens.
- Configurator server: user-facing message texts in `configurator/server.py` and `online.py` follow the word list; no route or field changes.
- Tests: a task test module (keyboard only, both themes), a word-list test, the disabled-reason check and forced-colours run in the layout test, and updated text expectations in existing page tests.
- Docs: `docs/wording.md` (new), `docs/configurator.md` (colours and icons legend, screenshots), `docs/tour.md`, `README.md`.
- Version: PC tools minor bump. No plugin change, so no hardware test.
- Order: applied after the other four overhaul changes, since the tree, Nodes table, connection bar and trace workspace are where the icons go and what the task tests walk through.
