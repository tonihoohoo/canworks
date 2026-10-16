# Wording on the configurator page

The configurator (`canworks-config`) uses one word for each thing and writes every label, button, tooltip and message the same way. This page is the list. `tools/deploy/tests/test_configurator_wording.py` checks the page's files and the configurator server's messages against the ruled-out terms in `tools/deploy/tests/data/wording/wording.json`.

Only text a person reads is checked: string literals with a space and a word in them. Identifiers and config keys (`bitrate`, `node_id`) are code, not wording. Text that comes from an EDS, a DBC or the user's config is data and is shown as it is.

## Terms

| Use | Not | Notes |
|---|---|---|
| bit rate | bitrate, baud, baudrate, kbps | CAN bit rate in kbit/s. "Serial speed (baud)" for an slcan adapter's serial line is the one exception: that line really is set in baud. |
| node ID | Node-ID, NodeID, node id | "Node ID" only at the start of a label. |
| COB-ID | COB ID, COBID, cob-id | |
| EDS, DCF, DBC | eds file, Eds | |
| runtime | PLC runtime, OpenPLC (for the connection target) | The thing a config connects to. |
| USB adapter | dongle, interface (in the UI) | "Adapter" alone once the context is clear. |
| **Allow changes** | write access, read-write mode | The lock in the connection bar: "Read-only" with **Unlock…**, or "Changes allowed" with **Lock**. |
| **Read all**, **Back up**, **Compare**, **Restore** | | Parameters actions, as buttons. |
| **Configure**, **Commission** | Online (as a place) | The two workspaces. |
| simulated | virtual, fake (for a node) | "Virtual" is kept for the virtual adapter and the virtual example. |
| OPERATIONAL, PRE-OPERATIONAL, STOPPED | Operational mode, preop | NMT states in capitals in tables, as the standard writes them; "Operational" in the legend and tooltips. |
| missing | not found, offline (for a node) | Configured, but did not answer. |

## Style

- **Sentence case** for labels, headings, tabs and buttons: "Add node from EDS…", not "Add Node From EDS…".
- **Buttons start with a verb**: "Save log", "Read all", "Connect…". A button that opens a dialog or needs more input ends with "…".
- **Units after a space**: "500 kbit/s", "100 ms", "1.5 s", "24 V". IEC literals such as `T#20ms` stay as they are.
- **Hex** with `0x` and upper-case digits: `0x6150:1`, `0x1A5`. Node IDs are decimal.
- **No prefixes** such as "Error:" or "Warning:"; the state icon says it.
- **No "please" and no exclamation marks.**
- **Messages say what happened, then what to do**, in one or two sentences: "The folder cannot be written. Pick another folder or change its permissions."
- **Empty states say what the area is for** and offer the action that fills it: "Startup SDO writes set objects on the device each time the master starts it. Add write…".
- **Disabled controls say why** in their tooltip: "Needs a connection with changes allowed".
- **No internal names** in messages: no config paths (`nodes[2].tx_pdos[1]`), no file system paths unless the path is the subject.

## Adding a term

Add a row to the table above and a rule to `wording.json` (`pattern` is a case-sensitive regular expression, `preferred` is what the test tells the author). Put exact phrases that may keep a ruled-out word, such as a quote of another tool's menu, under `allow`.
