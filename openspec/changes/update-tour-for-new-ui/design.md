## Context

`docs/tour.md` has 15 chapters and a closing "What needs hardware" section. Chapters 1, 4, 14 and the hardware section are command lines and editor steps; CI already runs their commands (`test/virtual-example/run.sh`) and they did not change. Chapters 2, 3, 5-13 and 15 are configurator steps written before today's UI overhaul. This document lists each stale step and the text proposed for it. Labels were checked against `tools/deploy/canworks/configurator/static/` on `main` (c2fa0ab) and against the open PRs' proposals.

## Goals / Non-Goals

**Goals:** a first-time user never has to look for a control: every step says workspace → tree entry or tool → node tab → control, with the page's own labels. Steps work in the order written. The tour stays right after future renames (label test).

**Non-Goals:** new chapters, a different example project, an in-page guided tour (the configurator has none, and this change does not add one), changes to the configurator.

## Decisions

### Connect through the bar only

Chapter 5 uses the path that is right both before and after `one-connect-place`: entering **Commission** opens the connect panel when this PC has no host and token for the project (`connection.js`, "Entering Commission connects at once when this PC has the runtime host and the token; otherwise the connect panel opens"). **Local simulator runtime** fills the host with `local`; **Connect** then asks for the token because this PC has none. No Configure → Online access detour.

### One "where" line per step, then what you see

Each configurator bullet starts with its place in bold path form, for example **Commission** → `io` → node 6 → **Status**. This is the form chapter 8 already uses and is the shortest unambiguous one.

### Label test with an allow-list, not a full page walk

A Playwright walk of the whole tour would be the strongest check but would add minutes to CI for a docs file (Toni's CI-minutes rule). A plain text test (bold labels vs. strings in the page code) costs seconds and catches the common drift, a renamed or removed control. The allow-list holds labels that are not the configurator's, and lead-ins such as **A deliberate mistake:**. Network and node names in backticks are not checked.

### Lines for unmerged changes are dropped, not hedged

The tour is read by people who download `main`. A line that describes a page they do not have is worse than a missing line. Apply checks what merged (task 1.1).

## Stale steps and proposed text

### Chapter 2. The configurator and its checks

| Now | Problem | Proposed |
|---|---|---|
| "on **Advanced** the configuration check, store sub-index 1, the NMT command byte and the TIME COB-ID" | NMT command byte is on **Supervision** | "on **Supervision** the NMT command byte, and on **Advanced** the configuration check with store sub-index 1 and the TIME COB-ID with the consumer bit" |
| "`cell`: the slave network ...; **Gateway** with its two routes ..." | Gateway is its own tree entry after the networks, not part of `cell` | "`cell` → **Bus** (the Bus and slave device page): the objects the program reads and writes. **Gateway**, the tree entry after the networks: its two routes, ..." |
| "the network tree on the left: `io`, `motion`, `cell`, `host`" | (#103) each entry now shows its protocol under the name | add: "each with its protocol under its name (CANopen master, CANopen slave)" |
| Deliberate mistake: "the tree and the PDOs tab show an error badge" | the badge reads `1✕` | "the tree entry and the **PDOs** tab show `1✕`" |
| (none) | (#100) Notes tab | new bullet: "`io` → node `rtd` → **Notes**: **My notes** is empty; **All notes** shows the built-in notes for its CiA 401 objects; **Add note…** gives 0x6110 your own." |

### Chapter 3. Exports

| Now | Problem | Proposed |
|---|---|---|
| "From the configurator's header, or from a terminal" | header has an **Export** menu; the slave EDS is not in it | "From the configurator's **Export** menu (**All DCFs**, **DBC**, **Documentation**) and `cell` → **Bus** (the Bus and slave device page) → **Export EDS**, or from a terminal" |

### Chapter 5. Online diagnostics

| Now | Problem | Proposed |
|---|---|---|
| "switch to **Commission** at the top and, in the connect form on the Nodes table, pick **Local simulator runtime** with the token `virtual-plant-demo`" | the form goes with `one-connect-place`; the token has no field there | "Switch to **Commission** at the top. The connect panel opens: press **Local simulator runtime**, then **Connect**, and enter `virtual-plant-demo` when the page asks for the token. The connection bar then shows the runtime." |
| "pick each network there" | networks are picked on the tree too | "Pick a network on the tree (or in the bar's network picker; they follow each other)" |
| "the TPDO 1 timeout line of node 5, the SDO variables of node 6, every 60 s an EMCY 0x5000 from node 5 ... in its **Emergency history**" | these are on the node's **Status** tab | "Click node 5 for its tabs: **Status** shows the TPDO 1 receive timeout and, every 60 s, an EMCY 0x5000 in **Emergency history** (the tree flags node 5 until you open Status). Node 6's **Status** shows its SDO variables." |
| "On node 6, **NMT** → **Reset node**" | needs the place | "Node 6 → **Status** → **NMT** → **Reset node**, and confirm: ... The **Log** at the bottom records the reset and the boot." |

### Chapter 6. Device parameters

| Now | Problem | Proposed |
|---|---|---|
| "`io` → node 6 → **Object dictionary**" | workspace missing | "**Commission** → `io` → node 6 → **Object dictionary**" |
| "edit 0x6110 sub 3 ... pick **Keep in configuration**: it becomes a startup SDO in the page, to save and upload" | where Save is | "... it becomes a startup SDO, the header shows **● unsaved**; **Save**, then upload as in chapter 4" |

### Chapter 7. Simulation and faults

| Now | Problem | Proposed |
|---|---|---|
| "**Simulation** in the configurator, network `io`" | Simulation is a tool tab with a network picker | "The **Simulation** tab, network `io` in its picker → **Live values**: click a device for **Values** and **Faults**." |
| node 6 **Heartbeat stop** | fine; a shorter path exists | add: "The same buttons are on a simulated node's **Status** tab in Commission (**Simulated device**), so a quick fault does not need the Simulation tab." |
| "the simulation file editor shows the `io` section" | tab name | "**Simulation file** shows the `io` section" |

### Chapter 8. LSS

| Now | Problem | Proposed |
|---|---|---|
| "**Scan the bus** compares the whole network with the config" | the page asks first while the PLC runs the nodes; the default is Cancel | "**Scan the bus** asks first, because the PLC program runs nodes 5-7: pick **Scan anyway**. It compares ..." |
| "the Nodes table then lists node 8 as **Not in config**" | (#99) device name shown | add: "with the device's name read from it" |

### Chapter 9. The drive

| Now | Problem | Proposed |
|---|---|---|
| "In **Commission** → `motion` → node 4, watch 0x6041 ..." | tab and control missing | "**Commission** → `motion` → node 4 → **Object dictionary**: tick **Watch** on 0x6041 (statusword; **Bits** names each bit), 0x6061 and 0x6064" |
| "In **Simulation** on `motion`, **Drive inputs…**" | path | "**Simulation**, `motion` → **Live values** → node 4 → **Faults** → **Drive inputs…**" |

### Chapter 10. Slave and gateway

| Now | Problem | Proposed |
|---|---|---|
| "from node 20's SDO panel on `host`" | the panel is on the Status tab | "from **Commission** → `host` → node 20 → **Status** (SDO panel)" |
| "**Commission** → `host` → node 20 → **NMT** → **Stop**" | tab | "... node 20 → **Status** → **NMT** → **Stop**" |

### Chapter 11. Trace with a trigger

| Now | Problem | Proposed |
|---|---|---|
| "**Trace**, network `io`" | tool tab and picker | "The **Trace** tab, network `io` in its picker: **Start**." |
| (none) | (#101) Decoding panel | new, last: "**Decoding** → **Add DBC…** with the `io.dbc` of chapter 3: the panel lists its messages as not used, because the config's own PDOs decode those identifiers first." |

### Chapter 12. Frame inspector

| Now | Problem | Proposed |
|---|---|---|
| "The **Sequences** tab shows node 6's boot as a story after the NMT reset of chapter 5" | no trace was recording in chapter 5, so there is no boot story | "With the trace still recording, reset node 6 again (**Commission** → `io` → node 6 → **Status** → **NMT** → **Reset node**; the trace keeps recording in the other workspace). Back on **Trace**, **Sequences** shows its boot as a story, and the SDO conversations of the SDO variables." |

### Chapter 13 and 15

Labels match the page (**Transmit list**, **Add frame**, **Send**; **Simulation** → **Machine**, **Follow tool**, **Tool path**, **Jam**). Chapter 13 adds where: "the **Trace** tab, under the trace". Chapter 15 step 2 adds "pick `motion` in the Simulation tab's picker".

### Screenshots

`tour-gateway.png` (Gateway page) and `tour-mistake.png` (the `%IB13` error) are retaken after the visual refresh and #103.

## Risks / Trade-offs

- [Several open PRs change labels the tour names] → apply after they merge (task 1.1); the label test catches what slips.
- [The label test can pass on a label that exists elsewhere in the page code] → accepted; it catches removals and renames, which is the drift seen so far.
