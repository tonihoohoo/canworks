## Why

`docs/tour.md` walks a new user through `examples/virtual-plant` and is the first thing the README offers ("Try it without hardware"). The configurator changed under it today: the shell with Configure | Commission and the connection bar, the network tree with node tabs, the Commission workspace with the Nodes table and node tabs, the Trace workspace, and the visual refresh. Several tour steps now send the user to controls that moved or no longer exist, and one step cannot work at all:

- **Chapter 5 connect** says to use "the connect form on the Nodes table" and to "pick **Local simulator runtime** with the token". The form is going away (change `one-connect-place`), and the token is never typed in a form: the page asks for it when it has none.
- **Chapter 2** puts the NMT command byte on **Advanced** (it is on **Supervision**) and the **Gateway** under `cell` (it is its own tree entry after the networks).
- **Chapter 12** says the **Sequences** tab shows node 6's boot "after the NMT reset of chapter 5", but chapter 5 runs before any trace records, so there is no boot to show.
- **Chapters 5, 6, 9 and 10** name a node feature without the node tab it lives on (Status, Object dictionary, Parameters), so the user has to hunt for it.
- **Chapter 8** does not warn that **Scan the bus** asks first while the PLC runs the nodes, and a user who picks the default (Cancel) sees nothing happen.
- The two screenshots (`tour-gateway.png`, `tour-mistake.png`) show the page before the visual refresh.
- Nothing stops the tour drifting again: CI runs the tour's command lines, but nothing checks the page labels it names.

## What Changes

- **Rewrite the UI steps of `docs/tour.md`** to the current page. Every step names where it happens, in the order the user looks: workspace, tree entry or tool tab, node tab, control. The full list of stale steps and their new text is in `design.md`.
- **Connecting** (chapter 5): **Commission** at the top; the connect panel opens by itself; **Local simulator runtime**, **Connect**, and the token `virtual-plant-demo` when the page asks for it. Written so it is right before and after `one-connect-place`: it uses only the bar's panel.
- **New where it helps a first-time user**: the state icons and the diagnosis flag on the tree (chapter 5), the bottom panel's **Log** recording the NMT reset (chapter 5), **Scan anyway** (chapter 8), the node's **Status** tab with its **Simulated device** panel as the quick way to inject a fault without leaving Commission (chapter 7).
- **Chapter 12** resets node 6 again while the trace records, so the boot story is there.
- **Features merged or in flight today** get one line each where they fit the walk: the two-line tree entries (chapter 2), the **Notes** tab's **My notes** / **All notes** (chapter 2), device names in the Nodes table (chapter 8), the Trace **Decoding** panel with the `io.dbc` from chapter 3 (chapter 11). A line whose change has not merged when this is applied is left out rather than describing a page the user does not have.
- **Retake** `docs/images/tour-gateway.png` and `docs/images/tour-mistake.png` on the current page, light theme, 1280 px.
- **New docs test** `tools/deploy/tests/test_tour_labels.py`: every bold label in `docs/tour.md` is found in the configurator's page code (`static/*.js`, `index.html`), apart from a short allow-list of labels that are not the configurator's (the editor's **Build and Upload**, GitHub's **Code → Download ZIP**, the tour's own lead-ins). A renamed button then fails CI with the label and the chapter. It runs in the existing Python test job, adding seconds.
- README: no change expected (it only links the tour); checked during apply.

No configurator, plugin, CLI or file format change.

## Depends on

Based on `main`. The tour must describe what a user who downloads the repository gets, so apply after these merge, or drop their lines:

| PR | Change | Tour lines that depend on it |
|---|---|---|
| (branch only) | `one-connect-place` | none required: chapter 5 already uses only the bar; chapters 7 and 11 lose their "or Connect… here" fallbacks once it merges |
| #99 | `name-nodes-and-standard-dictionary` | chapter 8: the found device's name in the Nodes table |
| #100 | `notes-tab-own-notes` | chapter 2: Notes tab **My notes** / **All notes** |
| #101 | `add-trace-eds-dbc-decoding` | chapter 11: **Decoding** → **Add DBC…** |
| #103 | `fix-clipped-text-configure` | chapter 2: protocol under each network name; also the retaken screenshots |
| #102 | `unify-dbc-import` | none (the example has no plain CAN network) |
| #97, #98 | merged | none |

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-virtual-example`: requirement **Guide** says each step names its workspace, page and tab, matches the current page, and is checked by a label test; the screenshots show the current page.

## Impact

- `docs/tour.md`, `docs/images/tour-gateway.png`, `docs/images/tour-mistake.png`.
- `tools/deploy/tests/test_tour_labels.py` (new).
- No tools version bump (docs and tests only).
