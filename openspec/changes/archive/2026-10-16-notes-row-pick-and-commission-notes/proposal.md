## Why

Two things make notes slower to work with than they should be.

**The Add note picker needs a button you often cannot see.** "Add a note: pick the object" lists every object of the EDS, but an object is chosen only with the small **Write** / **Edit** button at the right end of its row. With long object names the table is wider than the dialog, so that column is scrolled out of view and the user has to scroll sideways to find it. Clicking the row itself, which is what people try first, does nothing.

**Commission a device has a weaker Notes tab than the configurator.** In a config the Notes tab can add, edit and import notes. In Commission a device (no config) the same tab is read-only: no **Note** button, no **Add note…**, no **Import notes…**, only "open the device in a config". But commissioning is exactly when the user has the device and its manual in front of them and learns what an object does.

## What Changes

- **Pick an object by clicking its row.** In the Add note picker a click anywhere on a row picks that object and opens the Note editor. The Write / Edit button column goes away, so the table fits the dialog and nothing needs sideways scrolling. Rows show a hover tint and the keyboard row the same tint as the Object dictionary tab. Keyboard: Down from the search moves into the list, Up and Down move between rows, Enter picks the row (Enter in the search still picks the first match), Escape cancels.
- **Open a note by clicking its row on the Notes tab too**, so both lists behave the same. The row's **Note** button stays for keyboard and screen reader users. A click that selects text does not open the editor, so note text can still be copied.
- **Commission a device gets the same Notes tab as the configurator**: the three views, the count on the tab label, **Note** buttons and row clicks, **Add note…**, **Import notes…** with its preview, and **Export notes…** with **My notes** and **Merged with built-in**.
  - Commission a device has no Save, so a kept note or an import is written at once to the notes file next to the node's EDS (`<eds>.notes.json`, in the EDS library or wherever the EDS came from), using the same rules as the configurator's Save. A banner says where it went and offers **Undo**; Ctrl+Z also undoes the last note write.
  - Each note write and import is a line in the commissioning log.
  - The Object dictionary, Parameters and PDO test tabs show the new note at once.
  - When the notes file cannot be written (a read-only folder, an unreadable notes file), the tab stays read-only and says why, as today.
- **Notes follow the device into a config.** "Add to a config…" copies the EDS's notes file along with the EDS when the config has no notes file for it yet; when it has one, the config's file is kept and the banner says so.
- README and `docs/configurator.md` are updated.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-configurator`: Notes tab (row click; same tab in Commission a device), Add note picker (row pick, keyboard), Note editor (opened from row click), Note edits are draft edits (except in Commission a device), Notes read-only without a config (replaced), Commissioning log (note writes).
- `canopen-device-notes`: Import notes written at once in Commission a device; notes file copied with the EDS by Add to a config.

## Impact

- `tools/deploy/canworks/configurator/static/node.js` (picker and Notes tab rows), `nodes.js` (`commNotesTab` uses the editable tab), `app.js` (`notesEditable`, `editNote` save path in Commission a device), `commission.js` (log lines, Add to a config).
- `tools/deploy/canworks/configurator/server.py`: notes of an EDS path in Commission a device (`/api/state` or `od_entries`), a write endpoint for one note change set, `import_notes` allowed in Commission a device, notes file copied on Add to a config.
- Page tests for the picker and Commission notes; server tests for the write endpoint.
- No change to the notes file format, the runtime or the plugin. No hardware tests.
