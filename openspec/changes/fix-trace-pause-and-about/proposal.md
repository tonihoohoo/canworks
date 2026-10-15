## Why

Two small things in the Trace view get in the way of reading a live bus:

- In the By identifier view the **Pause view** button keeps its label while the view is paused. Only a faint pressed style and the status text say the table is frozen, so the button does not say what pressing it will do.
- In the frame inspector, opening **About this kind of message** works for a moment and then the section snaps shut. While the inspector follows a live identifier, each new frame rebuilds the inspector, which closes the section, drops the field the user was reading in the explanation box and jumps the inspector back to the top. The section only stays open while the view is paused.

## What Changes

- The pause button reads **Pause view** while the table updates and **Resume view** while it is paused, with a matching tooltip. Because the label now carries the state, the button stops using `aria-pressed` (a toggle should change its name or its pressed state, not both).
- The inspector keeps what the user opened when it moves to a newer frame: the **About this kind of message** section stays open (or closed) as the user left it, including for the next frames and other message kinds, until the user closes it. When the new frame is of the same identifier, the explained field stays in the box, the inspector keeps its scroll position, and focus stays where it was.
- The same rule holds wherever the inspector follows new frames (By identifier, Chronological following the newest frame, the Frame lab is unaffected as it does not refresh on its own).
- Configurator tools version 0.61.0 -> 0.61.1.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-configurator`: "Live updates of the By identifier view" (pause button label), "Frame inspector panel" (state kept across live updates).

## Impact

- `tools/deploy/canworks/configurator/static/trace_ids.js` (pause button), `explain.js` (`fxInspectSeq`, `fxMeaning`: carry the About state, picked field, scroll and focus into the rebuilt inspector).
- Browser test for both behaviours in the existing trace browser tests; no server or plugin change.
