## Context

File imports in the configurator today:

| Import | First click | File kept | Same-name conflict |
|---|---|---|---|
| + Add node… (tree) | system file picker (hidden `#eds-input`) | `pending`, written on Save | Replace / Keep both |
| Add node from EDS… (Commission) | system file picker (`.file-button`), then a node ID dialog | uploaded with `/api/eds` | Keep both, without asking |
| Use an EDS file… (slave) | system file picker (`.file-button`) | `pending` | Replace / Keep both |
| Import DBC… (J1939) | system file picker (`.file-button`) | `pending_dbc`, written on Save if `j1939.dbc` names it | Replace / Keep both |
| Open… (Trace, Transmit) | system file picker (`.file-button`) | — | — |
| **Import DBC… (CAN messages)** | **dialog with a raw `<input type=file>` and Next** | **no, name only** | **none** |

`rawImportDbc()` in `rawcan.js` reads the file text in the page and posts it to `/api/raw/dbc` (list) and `/api/raw/dbc_import` (entries); `raw.dbc` is set to the file name only when empty. `field("DBC file", "raw.dbc", "text")` makes it a free text input. Nothing reads the file `raw.dbc` names: the trace decodes configured raw messages from the config, not from the file.

**Goals:** the CAN messages DBC import behaves and looks like the J1939 one and the EDS imports; the config's DBC file travels with the config.
**Non-goals:** Trace DBC files (in-flight `add-trace-eds-dbc-decoding`, kept in per-user state), drag and drop, several DBC files per network, changing J1939's flow.

## Decisions

### File button, no intermediate dialog
`Import DBC…` becomes `el("label", {class: "file-button"}, "Import DBC…", input)` with `accept=".dbc,.DBC"`, the same element J1939 uses. The `change` handler resets the input (so the same file can be picked twice) and starts the import. Cancelling the system picker does nothing.
*Alternative:* keep a dialog but style the input. Rejected: every other import goes straight to the picker, and the dialog adds a step with no choice in it.

### Shared pending DBC store
`/api/raw/dbc` takes `{name, data}` (base64, as `/api/j1939/dbc` and `/api/eds`) and goes through the server's existing `import_dbc` path: name check, 409 with `conflict` for a different file of the same name, `on_conflict` `replace` / `keep_both`, the bytes kept in `pending_dbc` and in `pending_dir`. With only `name` it reads the network's file (`dbc_path`) for **Pick messages…**, 404 when it is missing. The parse step differs per page (`rawpage.dbc_messages` for raw, `j1939_dbc.load` for J1939), so `import_dbc` gets a `kind` argument that picks the reader and its "no messages" text; the store, conflict and file handling are shared.
`/api/raw/dbc_import` takes `name` instead of `text` and reads the bytes from `dbc_path`.
Save writes a pending file when any network names it in `j1939.dbc` **or** `raw.dbc`. One file may serve both pages of a J1939 network that also has raw messages.
*Alternative:* keep posting text and copy on Save from the page. Rejected: two paths for the same thing, and no conflict check.

### Read-only DBC line with Pick messages…
The `Network` fieldset loses the `raw.dbc` text field. A line above the message lists reads "Messages come from **name**." or "No DBC file yet."; when the config names a file that is neither in the folder nor pending it adds "(not in the config folder: import it again)" as a field warning. The toolbar holds **Import DBC…** and, when `raw.dbc` is set, **Pick messages…**. **Program may send protocol identifiers** stays in the fieldset (and **Listen only** on plain networks).

### Ask before a second file
When `raw.dbc` is set to a different name and the network has raw messages, importing asks, before the file is uploaded:
"The network's N messages come from a.dbc. Importing b.dbc makes it the network's DBC file; the messages from a.dbc stay." — **Keep a.dbc** (cancel) / **Use b.dbc**. Same shape as J1939's question; the raw wording says the messages stay, because raw messages carry their own layout (J1939's says the old PGNs are no longer described by the file, which is also true there).
After a successful import `raw.dbc` is set to the imported name (the conflict answer may have changed it to `name-2.dbc`).

### One picker
`pickDbcMessages({title, columns, rows, problems})` in a new `dbcpick.js` (loaded before `rawcan.js` and `j1939.js`) builds the modal: one `<select>` per row with **Leave out / Receive / Send** (Send omitted on listen-only networks), the preselection rule, an "already in received/sent messages" note with Leave out selected, a **Left out of the import (n)** `<details>`, and **Cancel / Add picked messages**. Each page passes its columns: J1939 Message, PGN, Sender, Length, Signals; CAN messages Message, Identifier, DLC, Cycle, Signals. "Already in" for raw compares identifier and extended flag per direction (the rule `rawpage.dbc_import` already applies); the server note for duplicates stays as a backstop.
Preselect Send: sender `PLC` (case-insensitive) or the network's name, plus J1939's own source-address rule.
`rawpage.dbc_messages` adds `problems` for messages it cannot import (none today beyond `mux_problem`, which stays on the row), so the list is usually empty and hidden.

### raw.dbc follows the messages
`rawRemove` clears `raw.dbc` with the last message, and then `raw` itself when nothing else is set. A pending file no network names is not written on Save (existing rule).

## Risks / Trade-offs

- [A config whose `raw.dbc` names a file the user keeps elsewhere now shows it as missing] → clean cut (not in real use); **Import DBC…** with that file fixes it, and the import has no other effect on existing messages.
- [Keeping the DBC file adds a file to the config folder, which goes to the PLC] → DBC files are small and J1939 already does it; the plugin ignores them.
- [Shared picker could change J1939 behaviour] → the J1939 page tests run unchanged against the shared code.
