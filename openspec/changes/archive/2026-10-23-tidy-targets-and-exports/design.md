## Context

Survey (2026-10-23, main 678e84c, tools 0.118.0): `examples/openplc-modbus` opened at 1440×900 and switched to Modbus bridge and to CODESYS on the Project page. Today:

| What | Where |
|---|---|
| Target field | Project page; New config dialog |
| OpenPLC facts (remote device, poll and requests, writer lost after, map hash, first editor location) | Project page, read-only table |
| OpenPLC settings (poll, remote device, first editor location, unit ID) | Modbus bridge page, OpenPLC box |
| Move into project…, New editor project… | Header Project ▾ (standalone OpenPLC only) |
| All DCFs, This node's DCF, DBC, Documentation | Header Export ▾ |
| Register map CSV, JSON, ST variables, Node-RED flow | Bridge page toolbar, for bridge and OpenPLC |
| Install on device… | Header primary; bridge page |
| Build into CODESYS project…, Download for CODESYS | Header split button (Download under ▾); CODESYS page |
| Copy as ST call | Commission OD and NMT, J1939 PGN, CAN message; every target and no config |

## Goals / Non-Goals

**Goals:** one rule a user can learn once for where things are; no export offered where it cannot work; the header one row from 1280 px with every chip; no change to what any export writes.

**Non-Goals:** new exports (PLCopen XML stays `add-plcopen-export`), changes to the command-line tools, a different tree, the Commission or Devices workspaces' layout.

## Decisions

### 1. The rule

| Place | Holds |
|---|---|
| Project page | The target, and actions on the project as a whole (OpenPLC: the editor project) |
| Header primary target button | Putting the config onto the target: Install on device… (Modbus bridge, OpenPLC), Build into CODESYS project… (CODESYS) |
| Export ▾ | Every file the configurator writes for download |
| Target page (Modbus bridge, CODESYS) | That target's settings; the register map table and Pack for Modbus |
| Per item | Copy as ST call, and exports of one item (slave EDS, device notes) |

*Alternative:* each export on the page it concerns (today's bridge page model) and the menu for network-wide files only. Rejected because a user cannot tell where an export lives without knowing which page "owns" it, and PLCopen would add a sixth button to an already long page.

*Alternative:* program-side exports under the target button's ▾. Rejected because downloads would then sit in two menus; the target button stays one action.

### 2. Export ▾ groups

Two labelled groups in one panel. *Network files* never depends on the target. *For the program* lists the target's own:

| Target | For the program |
|---|---|
| Modbus bridge | Register map (CSV), Register map (JSON), ST variables, Node-RED flow; later For another PLC (PLCopen XML)… |
| OpenPLC | Register map (CSV), Register map (JSON), ST for another PLC |
| CODESYS | Download for CODESYS |

OpenPLC gets no Node-RED flow (OpenPLC's Modbus master is the only writer, on 127.0.0.1). Its ST item is named **ST for another PLC**: on an OpenPLC config the `.st` export is the PLC link file a second Modbus PLC uses with the library (`docs/plc-library.md`, "On another Modbus PLC"), not a variable list for OpenPLC itself, which Save writes into the editor project. The group is hidden when it would be empty: on a config whose networks the target cannot export, for example a CODESYS config with no CANopen master network, which already disables Download. Each item keeps its existing route, progress and Problems behaviour ("Exports report progress and keep Problems clean").

The bridge page's register map heading keeps Pack for Modbus and one line, "Export ▾ → For the program has the register map files.", so nobody who learned the old buttons is lost.

### 3. Project page owns the editor project

An OpenPLC config's Project page gets an **Editor project** section under the target:

- project mode: the project's name and folder, and what Save writes there (the file list from today's facts paragraph);
- standalone mode: "No editor project: PLC addresses are not checked against a program." with **Move into project…** and **New editor project…** (the same dialogs).

The header Project ▾ goes away; the header then has no item named "Project", and the Project page is the only one. The `ui:editor_project` row in `targets.py` keeps hiding the section on other targets.

### 4. One name per target

`targets.TITLES` becomes the only name in the page and in messages: "OpenPLC", "Modbus bridge", "CODESYS". `LABELS` ("the Modbus bridge", "OpenPLC through Modbus") is used only where grammar needs an article ("settings the Modbus bridge does not use"), and its OpenPLC value becomes "OpenPLC". The removed plugin's message and its button **Switch to OpenPLC through Modbus** keep their wording (the contract and deploy tool name that button; it is the one place where "through Modbus" explains the conversion). New config's first choice reads "OpenPLC", and its sentence keeps "OpenPLC Runtime". The Modbus bridge choice's sentence also names "another PLC".

### 5. OpenPLC facts on the bridge page

The read-only facts become rows at the top of the OpenPLC box on the Modbus bridge page. These are the remote device and port, requests per poll with the warning above 40, writer lost after, map hash, and the first editor locations, placed next to the poll and remote device fields they follow from. The Project page keeps the target and the Editor project section. Problems keeps its request-count warning and links to the poll field.

### 6. Header width and menu placement

The spec already asks for one header row from 1280 px. The simulation chip breaks that for runtime targets: its full text "Simulated: the network (nodes 5, 6)" plus Details. When the row would wrap, the chip shows its icon and "Simulated" only, with the full text in its tooltip and in Details. A menu panel is right-aligned under its button unless that would cross the window's left edge; then it is left-aligned. One helper places every header menu: Export, ⋯ and Settings.

### 7. Copy as ST call visibility

The canworks blocks exist only in a program that talks to canworks-bridge: OpenPLC (the editor library), or any bridge client using the library's ST. So `usedBy("ui:st_calls")`, a new `targets.py` row for Modbus bridge and OpenPLC, decides. Commission a device without a config has no target and shows none. When the block needs a part the config does not have, the button stays enabled and the hint names the setting:

| Block | Needs |
|---|---|
| `CO_SDO_READ`/`CO_SDO_WRITE` | SDO bridge registers |
| `_BYTES`, `_STRING`, `_REAL` SDO blocks | request mailbox |
| `CO_NMT` | control block |
| CAN and J1939 send/request blocks | request mailbox |
| receive blocks | receive mailbox |

For example, "Needs the Function blocks' receive mailbox (Modbus bridge page)." The same text goes in the copied ST's first comment, so the code explains itself when pasted.

## Risks / Trade-offs

- **People who learned the bridge page's buttons.** The hint line on the bridge page and the tour line cover it. The project is not in real use yet, so there is no migration.
- **Export ▾ grows to about nine items on a bridge config with PLCopen.** Two group headings keep it scannable; it stays smaller than the bridge page toolbar plus menu today.
- **Copy as ST hidden on CODESYS.** A CODESYS user who wanted ST to adapt by hand loses it. CODESYS has its own CiA 405 SDO blocks, and canworks code there would not compile.

## Migration Plan

None (clean cut, no saved state changes).

## Open Questions

None.
