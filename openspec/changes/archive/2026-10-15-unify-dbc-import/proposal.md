## Why

Every other file import in the configurator works the same way: one click on the button opens the system's file picker (**+ Add node…** in the network tree, **Add node from EDS…** in Commission, **Use an EDS file…** on a slave, **Import DBC…** on a J1939 network, **Open…** in Trace). The file is kept with the draft and written into the config folder on **Save**, and a different file of the same name asks whether to replace it or keep both.

**Import DBC…** on the **CAN messages** page does none of this:

- **An extra dialog in the way.** The button opens a small dialog, "Import messages from a DBC file:", holding the browser's raw *Choose File / No file chosen* control and a **Next** button. It takes three clicks to reach the file picker and back, the control does not match the page's buttons, and **Next** with no file chosen silently closes the dialog.
- **The file is not kept.** Only the file's name is stored in `raw.dbc`. The file itself is never copied next to `canworks.json`, so `raw.dbc` points at nothing on another PC, on the PLC or after the original file moves. The docs say the trace decodes with it; it cannot.
- **"DBC file" looks editable but means little.** It is a free text field (placeholder "none") that the user can type any name into. It is not updated when a second DBC is imported (the first name stays), and it is not cleared when every imported message is removed.
- **A second import is silent.** On J1939, importing a different DBC on a network that already has messages from one asks first; on CAN messages it just adds.
- **The message picker differs from the J1939 one.** Lower-case **receive / send / skip** against **Receive / Send / Leave out**, no "already in received messages" mark (duplicates are only named in a message after the import), messages the import leaves out are not listed, and the buttons read **Import** against **Add picked messages**.

## What Changes

- **Import DBC… opens the file picker directly**, as a file button like **Import DBC…** on J1939 and **+ Add node…**. The intermediate dialog goes away.
- **The DBC file is kept with the config.** The chosen file is held with the draft and written into the config folder on **Save** when a network names it, sharing the store the J1939 import already uses. A different file of the same name asks **Replace** or **Keep both** (the new one gets a `-2` suffix), exactly as for EDS and J1939 DBC files.
- **The DBC file line is read-only.** The "DBC file" text field is replaced by the line the J1939 page has: "Messages come from **bus.dbc**." or "No DBC file yet.", with **Pick messages…** next to **Import DBC…** to open the picker again on the network's file (for messages left out the first time). A file the config names but the folder does not have is shown as missing, and **Import DBC…** fixes it.
- **Importing another DBC asks first** when the network has messages from a different file, naming both, like J1939. Picking it makes it the network's `raw.dbc`.
- **One message picker for both pages.** The CAN messages picker uses the J1939 picker's layout and words: **Receive / Send / Leave out** per message, Send preselected for messages a `PLC` node (or a node named like the network) sends, messages the network already has marked "already in received/sent messages" and left out by default, a **Left out of the import (n)** list for messages the file has but cannot be imported, and **Cancel / Add picked messages**. The CAN messages picker keeps its own columns (identifier, DLC, cycle, signals).
- **raw.dbc follows the messages.** Removing the last raw message clears `raw.dbc`.
- Docs (`configurator.md`, `raw-can.md`) and README describe the new flow and stop claiming the trace reads `raw.dbc`.

J1939 **Import DBC…** already works this way; it only moves onto the shared picker code, with no visible change. Clean cut: no migration for configs whose `raw.dbc` names a file that is not in the folder; they show it as missing.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-configurator`: Import a DBC into CAN messages (file picker, kept file, read-only DBC line, ask on a second file, shared picker).
- `can-raw-messages`: `raw.dbc` names a file in the config folder.

## Impact

- `tools/deploy/canworks/configurator/static/rawcan.js` (Import DBC button, DBC line, picker), `j1939.js` (picker moved into a shared helper), `app.js` or a new small `dbcpick.js` for the shared picker.
- `tools/deploy/canworks/configurator/server.py`: `POST /api/raw/dbc` takes `name` and `data` (base64) like `/api/j1939/dbc`, keeps the file in `pending_dbc` with the same conflict answer, or reads the network's file when only `name` is given; Save writes pending DBC files named by a raw or J1939 network; `rawpage.py` reads from bytes.
- Tests: `test_configurator_raw_page.py` (picker, conflict, second file, missing file, save writes the file), server tests for `/api/raw/dbc` and save.
- No plugin, config schema shape or CLI change. Not overlapping in-flight changes: Trace DBC files (`add-trace-eds-dbc-decoding`) stay in per-user state outside the config folder; this change only covers the config's own DBC.
