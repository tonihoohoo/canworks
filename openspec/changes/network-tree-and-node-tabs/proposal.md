## Why

This is the second of five changes in the configurator's UI overhaul, after `ui-shell-and-connection`. That change gives the page its shell: two workspaces, tool tabs, the connection bar, the status bar and the bottom panel. What is left of the side bar after it is still hard to work with:

- **Navigation is split.** Networks are tabs in a bar above the side bar, each network's nodes are a list under it, and the gateway, Modbus bridge, PDO links and CAN messages are loose buttons below. A config with two networks shows only one network's nodes at a time.
- **A node page is one long scroll.** Node, Supervision, Emergency, Axis, Advanced, Inputs, Outputs, Startup SDO writes and SDO variables are one page of 4,000 to 5,000 px. The section index helps to jump, but the page still holds everything at once.
- **Problems are only a list.** The node list shows an error count, but nothing shows which part of the node holds it, and a network that is not open shows nothing at all.
- **Config-wide settings sit under one network.** Online access is set for the whole config, but it is a section of the first network's Bus and master page.

The tools compared in the research all use the same pattern: a network tree as the only navigation, problems and state shown on the tree, and a device edited in tabs (General, PDO, SDO, status).

## What Changes

- **Network tree.** A tree replaces the side bar, the network bar and the node list, in both workspaces of a config:
  - one entry per network, with its protocol;
  - under each network: Bus and master (or Bus and ECU, or Bus), its nodes by node ID, **Add node…**, PDO links and CAN messages, as the network has them today;
  - after the networks: Online access, Gateway and Modbus bridge (when the config has them), and **Add network…**.

  Rename, role and Remove of a network move to a menu on the network's entry. The tree follows the ARIA tree pattern: one tab stop, arrow keys, type-ahead.
- **Node tabs.** A node page in Configure becomes tabs:
  - **General**: node ID, name, EDS and Simulated;
  - **PDOs**: inputs and outputs, each PDO with its mapping and a one-line summary of its settings that opens to edit them;
  - **SDOs**: startup SDO writes and SDO variables;
  - **Supervision**: heartbeat or guarding, status bit, state byte, NMT command, boot error and the EMCY settings;
  - **CiA 402**: only when the EDS has 0x6040 and 0x6041, or the node already has an axis;
  - **Simulation**: only for a simulated node, with its value sources and faults at start from `simulation.json`;
  - **Notes**: the objects of its EDS that have a note, with the Note editor and Export merged notes;
  - **Advanced**.

  The section index is removed. The open tab is kept when moving to another node and comes back after a reload.
- **Problems as badges.** Every tree entry and every node tab shows its count of errors and warnings, with shape and text as well as colour. A collapsed network shows the sum of its entries. Clicking a problem selects its tree entry and tab and focuses the field.
- **Simulated and absent marks.** Simulated nodes have a hollow mark and absent nodes a dashed one in the tree, in both workspaces.
- **Commission with a config.** The same tree is the navigation. A network entry opens its node table, a node entry the node's live tabs (Overview, Object dictionary, Parameters). Picking a node on another network moves the connection bar's network picker, and the picker selects that network in the tree.
- **Online access** becomes its own tree entry, out of Bus and master, because it is one setting for the whole config. The connection bar's read-only lock points there.
- **BREAKING (UI only):**
  - The network bar and the side bar's node list are removed.
  - The node page's section index is removed.
  - Online access moves out of Bus and master.

  No file format, server protocol or CLI changes.

Out of scope:
- Commission a device keeps its own Nodes tab; its device list joins the tree in `commission-workspace`, together with the Nodes table, scan comparison and node Status and Log tabs.
- Live NMT state and EMCY flags on the tree (`commission-workspace`, which builds on this tree).
- The final state colours and icon set (`visual-refresh`).

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-configurator`: network tree, node tabs, PDOs, SDOs, Notes and Simulation tabs, problem badges, the tree in Commission with a config; the workspaces, tool tabs, keyboard, narrow layout, simulated marks, problem messages, DCF export, network role, online access, Allow changes and network picker requirements follow; the network bar and node page sections are removed.

## Impact

- Configurator page: `tools/deploy/canworks/configurator/static/`
  - `index.html`, `style.css`;
  - `app.js`: the side bar, network bar and node page move out into the new modules `tree.js` (tree, badges, marks) and `node.js` (node tabs);
  - `links.js`, `rawcan.js`, `bridge.js`, `j1939.js`, `sim.js`: opened from the tree instead of the side bar;
  - the Commission workspace's online view in `app.js`.
- Configurator server: `ui.json` keeps the expanded networks and the open node tab per folder. No other server change.
- Tests: page tests moved from side bar clicks to tree helpers; new tests for the tree (keyboard, badges, simulated marks), node tabs, problem navigation and the layout fit at 1000, 1280 and 1440 px; axe-core on the tree and the tabs.
- Docs: `docs/configurator.md`, `docs/tour.md`, `docs/simulator.md`, `README.md`.
- Version: PC tools minor bump. No plugin change, so no hardware test.
- Order: builds on `ui-shell-and-connection` and modifies four of its requirements (Workspaces, Tool tabs, Allow changes in the connection bar, Network picker), so it is applied and archived after that change.
