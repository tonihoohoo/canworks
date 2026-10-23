## Why

The configurator's targets work well. There is one place to pick the target, the switch has Undo, and settings the target does not use are hidden. The files the configurator hands out, though, are spread over four places with no rule behind them:

- the header's **Export ▾** menu (DCFs, DBC, Documentation);
- five buttons on the Modbus bridge page (register map CSV, JSON, ST variables, Node-RED flow, next to Pack for Modbus);
- the ▾ of the CODESYS header button (Download for CODESYS);
- Copy as ST call on single items.

A user looking in Export ▾ for the Node-RED flow does not find it there. `add-plcopen-export` would add a sixth button to the bridge page.

Running the configurator on the OpenPLC example at 1440 px as all three targets also turned up the following:

- **Export menu off screen.** With the simulation chip shown, the header of an OpenPLC or Modbus bridge config wraps to two rows, although the spec asks for one row from 1280 px. Export ▾ then sits at the left edge, and its right-aligned panel opens mostly outside the window.
- **"Project" means three things.** The header has a **Project ▾** menu for the OpenPLC Editor project (Move into project…, New editor project…). The tree's **Project** page holds the target and Online access. CODESYS has a **Project file**.
- **One target, four names.** The same target reads "OpenPLC" (target field, header), "OpenPLC Runtime" (New config), "OpenPLC through Modbus" (messages) and "Modbus bridge for OpenPLC" (bridge page heading).
- **OpenPLC facts and settings apart.** The Project page shows the poll, remote device and map hash as a read-only table. The same poll and remote device are edited on the Modbus bridge page.
- **Exports that cannot work on OpenPLC.** An OpenPLC config offers Export Node-RED flow and Export ST variables. OpenPLC's Modbus master is the only writer on 127.0.0.1, so a Node-RED flow cannot write, and Save already writes the variable list into the editor project.
- **Copy as ST call where the blocks do not exist.** Commission offers Copy as ST call on a CODESYS config and when a device is commissioned without a config. The copied code calls canworks blocks that only an OpenPLC or bridge client program has.

## What Changes

- **One rule for where things are.** It is written down in the spec and in `docs/configurator.md`:
  - The **Project page** holds the target and the target's project-level actions.
  - The **header's primary target button** puts the config onto the target: Install on device… or Build into CODESYS project….
  - **Export ▾** holds every file the configurator writes for download.
  - The **target page** (Modbus bridge, CODESYS) holds settings, the register map table and Pack for Modbus.
- **Export ▾ in two groups.** *Network files* holds All DCFs, This node's DCF, DBC and Documentation, as today. *For the program* depends on the target:
  - Modbus bridge: Register map CSV, Register map JSON, ST variables, Node-RED flow.
  - OpenPLC: Register map CSV, Register map JSON.
  - CODESYS: Download for CODESYS.

  The bridge page's register map toolbar keeps Pack for Modbus and points to Export ▾. The CODESYS header button becomes a plain button with no ▾. The CODESYS page keeps its Build and Download buttons.
- **The editor project moves to the Project page.** An OpenPLC config's Project page gets an **Editor project** section. In project mode it shows the project's name and folder. In standalone mode it says there is none and offers **Move into project…** and **New editor project…**. The header's Project ▾ menu is removed.
- **One name per target.** The targets are called "OpenPLC", "Modbus bridge" and "CODESYS" everywhere: target field, header, New config, messages, check warnings and page headings. The sentence under each choice says how it runs. The bridge page of an OpenPLC config is headed "Modbus bridge", with one line saying OpenPLC reads and writes these registers.
- **OpenPLC facts next to their fields.** The read-only facts move from the Project page to the OpenPLC box of the Modbus bridge page: remote device and port, requests per poll with the warning above 40, writer lost after, map hash, and the first editor locations. What Save writes into the editor project moves to the Project page's Editor project section.
- **Header stays one row and menus stay on screen.** From 1280 px the header stays one row for every target, also with the simulation chip, which shrinks to its icon and "Simulated" when space is short. A header menu panel opens inside the window: it opens to the right when right-aligning would cross the window's left edge.
- **Copy as ST call only where the blocks run.** Every Copy as ST call (object dictionary, NMT, CAN message, J1939 PGN) shows only for OpenPLC and Modbus bridge configs. It is not shown on a CODESYS config or when commissioning a device without a config. When the bridge config lacks the part a block needs (a mailbox part, or the SDO or control registers), the button's tooltip and the copied text's first comment name the setting to turn on.

Not changed: the target switch and its Undo, target-relevant hiding, the tree, the DCF, DBC and Documentation exports themselves, the slave EDS and device notes exports on their own pages, and the command-line tools.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `canopen-configurator`: header menus, Export ▾ groups, header target action, CODESYS actions, register map buttons, OpenPLC project page, project target names, New config wording and Copy as ST call visibility. "Node-RED flow export on the bridge page" is replaced by the Export ▾ entry.

## Impact

- **Configurator page:** `index.html` (Export ▾ groups, no Project ▾, no target ▾), `app.js` (render: menu items per target, Copy as ST visibility, menu placement), `bridge.js` (toolbar, OpenPLC facts), `target.js` (Project page Editor project section, names), `tree.js` if labels change, `style.css` (sim chip compact form, menu placement); `targets.py` `LABELS`/`TITLES`, which give one name per target.
- **Server:** no new route. The existing export routes are called from the menu.
- **Tests:** extend the existing page tests (`test_configurator_layout.py` for the header row and menu placement with the sim chip, `test_configurator_bridge_page.py`, `test_configurator_codesys_page.py`, `test_configurator_openplc_modbus_page.py`, `test_targets.py`). No new page test file, so CI time stays flat.
- **Docs:** `docs/configurator.md` (where things are), `docs/modbus-bridge.md` and `docs/codesys.md` (button locations), README if it names a button, and the tour lines.
- **Order:** apply after `openplc-modbus-followups`, which also edits the OpenPLC Project page, and before `add-plcopen-export`. Its **Export for another PLC…** then goes into Export ▾ → For the program, on Modbus bridge configs only.
