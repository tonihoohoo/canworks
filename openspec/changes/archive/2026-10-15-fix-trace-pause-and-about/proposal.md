## Why

Two small things in the Trace view get in the way of reading a live bus:

- In the By identifier view the **Pause view** button keeps its label while the view is paused. Only a faint pressed style and the status text say the table is frozen, so the button does not say what pressing it will do.
- In the frame inspector, opening **About this kind of message** works for a moment and then the section snaps shut. While the inspector follows a live identifier, each new frame rebuilds the inspector, which closes the section, drops the field the user was reading in the explanation box and jumps the inspector back to the top. The section only stays open while the view is paused.
- In the Chronological view, the bottom row is cut in half while following a recording. Worse, the window drawn while following starts two rows too early, so the newest frames sit hidden under the bottom edge.
- In Sequences, picking an SDO conversation (or a boot story) redraws the list, which jumps back to the top, so the user loses the row they just picked.

## What Changes

- The pause button reads **Pause view** while the table updates and **Resume view** while it is paused, with a matching tooltip. Because the label now carries the state, the button stops using `aria-pressed` (a toggle should change its name or its pressed state, not both).
- The inspector keeps what the user opened when it moves to a newer frame: the **About this kind of message** section stays open (or closed) as the user left it, including for the next frames and other message kinds, until the user closes it. When the new frame is of the same identifier, the explained field stays in the box, the inspector keeps its scroll position, and focus stays where it was.
- The Chronological list draws the rows that are really in view, moved by the part of a row scrolled past the top. At the end of the list the newest row ends exactly at the bottom edge, so the row cut short (if any) is the oldest one at the top. Scrolling also becomes smooth instead of jumping a row at a time.
- Picking a conversation or boot story keeps the list's scroll position and the page position, and the picked row keeps focus.
- The same rule holds wherever the inspector follows new frames (By identifier, Chronological following the newest frame, the Frame lab is unaffected as it does not refresh on its own).
- Configurator tools version 0.61.0 -> 0.61.1.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-configurator`: "Live updates of the By identifier view" (pause button label), "Frame inspector panel" (state kept across live updates); new requirements "Newest frame whole in the Chronological view" and "Picking a sequence keeps the list in place".

## Impact

- `tools/deploy/canworks/configurator/static/trace_ids.js` (pause button), `explain.js` (`fxInspectSeq`, `fxMeaning`: carry the About state, picked field, scroll and focus into the rebuilt inspector; `fxPickSequence`), `trace.js` (`listWindow`, `refreshRows`, `drawRows`).
- Browser test for both behaviours in the existing trace browser tests; no server or plugin change.
