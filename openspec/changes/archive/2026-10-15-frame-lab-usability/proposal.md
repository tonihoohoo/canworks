# Proposal

## Why

The Frame lab and the Trace view's frame inspector are hard to use:

- Once opened, they are hard to close. The inspector hides only through a small button above the list, and a Frame lab result has no close at all.
- Results land where the user is not looking. In windows narrower than 1280 px the inspector opens below the fold, and in the Frame lab the result appears under every form.
- The explanation is very tall. The simulation banner takes four or five lines on every page, and the layers of the inspector cannot be folded.

A walk through on 2026-10-15 at 1440 and 1000 px also found two wrong displays: "Node ID null" on SYNC and NMT frames, and an arbitration Bus row that keeps using the bits of the sender that lost.

## What Changes

Trace inspector:
- The inspector gets a close button (✕) in its own title bar, and Esc closes it.
- A closed inspector leaves a slim **Inspector** rail that opens it again, and selecting a frame also opens it.
- In windows narrower than 1280 px the list and the inspector share the window height, each scrolling on its own, so a selected frame's explanation is always in view.

Inspector layers:
- The layers (Identifier, Data bits, On the wire) fold, and their folded state is kept on this PC for both Trace and Frame lab.
- The data grid is compact: smaller bit cells, and a field of whole bytes that is unused or all zero shows as one row that opens to its bits.
- The side box moves under the layers when there is no room beside them.

Frame lab:
- Two columns at 1280 px and wider: the frame box with **Examples | Build | Arbitration** tabs on the left, and the result on the right, staying in view.
- In narrower windows the result opens right under the frame box, and the page scrolls to it.
- The result has a **Clear** button. Example frames are grouped per node in a compact picker.

Simulation banner:
- The banner on every page shows one line, for example "Simulated: io (nodes 5, 6, 7), motion (node 4), cell, host. Do not upload as it is." Its **Details** opens the full text.

Fixes:
- Frames without a node ID (NMT, SYNC, TIME) no longer show "Node ID null". Their node bits are captioned as part of the identifier.
- After the deciding bit, the arbitration Bus row carries only the winner's bits.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `canopen-configurator`: the frame inspector panel (folding layers, compact grid, close and reopen), docked inspector layout in narrow windows, the Frame lab view layout (columns, mode tabs, Clear, result in view, arbitration bus row), and a one-line simulation banner.
- `canopen-frame-explain`: the identifier layer of frames whose function code carries no node ID.

## Impact

- Code: `tools/deploy/canworks/configurator/static/` (`explain.js`, `trace.js`, `trace_ids.js`, `app.js` banner, `style.css`), plus the trace prefs saved on this PC (`trace.json`), which get the layers' fold state. Nothing changes in the plugin, the runtime or the explanation model.
- Tests: browser tests for the configurator: `test_configurator_explain_page.py`, `test_configurator_layout.py`, `test_configurator_ux_page.py`, the e2e keyboard walk, and the trace page tests that click "Hide inspector".
- Docs: `docs/frame-inspector.md`, `docs/configurator.md` (Trace and Frame lab), `docs/tour.md`, README (Trace line), and the screenshots `docs/images/frame-inspector.png` and `docs/images/frame-lab.png`.
- No hardware test needed: the PC tools only.
