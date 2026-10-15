## Why

On the Nodes tab of **Commission a device**, the **EDS library folder** is a plain text field. To set it the user has to know the folder's full path, switch to the file manager, copy the path and paste it in. A typo only shows up as "… is not a folder" after leaving the field, and nothing says whether the folder actually holds any EDS files, so a wrong folder looks the same as a right one until a scan finds no matches. Every other place on the page that picks a file uses a button, so the text field also stands out as the odd one.

## What Changes

- **Button instead of a text field.** The EDS library row shows the chosen folder as text (or "None chosen") with a **Choose folder…** button and, when a folder is set, a **Clear** button. The text field goes away.
- **Folder dialog.** **Choose folder…** opens a dialog that browses the PC's folders through the configurator's own server, the same way the start page browses for a project: the current path with **Up**, a path field with **Go** for pasting a path, and the list of subfolders. Each subfolder that directly holds EDS files shows how many. The dialog opens in the current library folder (or its nearest existing parent), else the home folder. **Use this folder** sets it; **Cancel** changes nothing.
- **Drives on Windows.** **Up** from a drive root lists the PC's drives, so a library on another drive (such as `D:\`) can be reached without typing.
- **Says what it found.** After a folder is chosen the row says how many EDS files it holds with its subfolders ("34 EDS files"), or that it holds none. The count stops at a limit so a very large folder (such as the home folder) cannot stall the page; above it the row says the folder is large and scanning may be slow.
- **Matching unchanged.** Choosing or clearing the folder re-matches the devices already scanned, as editing the field does today. The folder stays a setting of this PC, not of any project.

No config file, CLI or deploy change. The settings API keeps `eds_library`; `/api/folders` gains a drive list on Windows and an EDS count per folder.

## Default picked

The dialog is drawn by the page and lists folders through the configurator's server, not the operating system's native folder dialog. The configurator is a local web server opened in a browser: a browser folder picker (`showDirectoryPicker`, `webkitdirectory`) never tells the page the folder's path, and a native dialog opened by the server (tkinter or a platform call) can open behind the browser window, is missing on some Python builds and Linux desktops, and blocks a server thread while open. The server-side browser already exists for the start page, works the same on Windows, macOS and Linux, and keeps keyboard and screen reader behaviour under the page's own tests.

## Out of scope

The other typed folder fields (**Add to a config…**, **move into project**, **New editor project**'s parent folder) keep their text fields in this change. The dialog is built so they can use it later.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
canopen-configurator

## Impact

- `tools/deploy/canworks/configurator/static/commission.js` (Nodes tab row), `static/app.js` (shared folder dialog), `static/index.html`, `static/style.css`.
- `tools/deploy/canworks/configurator/server.py` (`list_folders`: drives, EDS counts) and `online.py` (bounded EDS count for the settings reply).
- Page tests for the Nodes tab and the dialog; `docs/configurator.md`; README if it mentions the field.
