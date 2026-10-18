# Proposal: simplify-start-page

## Why

The configurator's start page has four equal cards: Open OpenPLC Editor project, Open standalone config, New standalone config and Commission a CANopen device (Toni, 2026-10-18: "explore how to make this better and simpler"). The explore found:

- **Two of the cards do the same thing.** The server already tells an editor project from a config folder by `project.json` (`/api/open` takes `mode: "auto"`), the folder list already tags folders "editor project" and "canworks.json", and Recent and the command line already open either kind. Splitting them makes the user pick the right card first and adds a "wrong card" dialog when they don't.
- **The cards don't act.** Three cards only select a mode and retitle the folder browser below, and the action is a separate "Open this folder" button. The fourth card (Commission) acts at once. Four cards that look the same behave two different ways.
- **Recent is last**, under a folder browser that is always open, although it is how a returning user opens their work.
- **The target is hidden.** The intro names OpenPLC, the Modbus bridge and CODESYS, but the choice appears only after "New standalone config", as a small switch above the browser. Node-RED, reached through the Modbus bridge, is not mentioned.
- **Internal words** on the first screen: "canworks/ folder", "canworks.json", "LSS", "object dictionary".
- For OpenPLC, starting a project-backed config takes two steps (new standalone config, save, then Project → New editor project… or Move into project…).

## What Changes

- The start page becomes a purpose line, two buttons (**Open…**, **New config…**), a quieter **Commission a device without a config** link, and **Recent** as the main content. The always-open folder browser and the four cards go.
- **Open…** opens the existing folder dialog (the one the EDS library uses). The picked folder opens as an editor project when it has `project.json`, else as a config folder when it has `canworks.json`. A folder with neither asks once: "Start a new config here?" (opens the New config dialog with that folder).
- **New config…** is one dialog: first "What will run the networks?" with three choices (OpenPLC Runtime; Modbus bridge, which names Node-RED, HMIs and other Modbus TCP clients; CODESYS), then the folder, then for OpenPLC a tick "Also create an OpenPLC Editor project here" (on by default when the editor's `openplc-cli` is found, disabled with the reason otherwise). With the tick, the new folder is an editor project with an empty config in its `canworks/` folder; without it, a config folder as today.
- **Recent** rows show the folder name, its path, a tag with the target (OpenPLC, Modbus bridge or CODESYS) and the kind (editor project or config folder), and when it was last opened. One click opens it; Remove sits on the row as a small button.
- **First run** (Recent empty): three short starting cards replace the empty list: "I have an OpenPLC project" (Open…), "Start something new" (New config…), "I just want to talk to a device" (Commission).
- Commission a device keeps its behaviour; only its entry point changes.
- The user-facing words "standalone config" become "config folder" on the start page and in its messages. The Project menu (Move into project…, New editor project…) stays as it is.

No config format, command-line or runtime change.

## Capabilities

### Modified Capabilities
- `canopen-configurator`: the start page (Choose what to edit), opening and creating folders (Folders the configurator cannot use), and the target of a new config.

## Impact

- `tools/deploy/canworks/configurator/static/index.html`, `app.js` (renderStart, startOpen, openFolder), `style.css`.
- `configurator/server.py`: Recent entries carry the target; new-config request with the target and an optional editor project; whether `openplc-cli` was found in the state.
- Browser tests that open folders through the start page (a shared helper and `test_configurator_page.py`), `test_configurator_layout.py`.
- `README.md`, `docs/configurator.md`, `docs/pc-adapter.md`, `docs/trace.md`, `docs/tour.md` wording.
